"""LLM-selected task execution inside one explicit, bounded operator authorization."""
import asyncio
import copy
from datetime import datetime,timezone
import json
import math
import os
import re
from pathlib import Path
import threading
import time
from uuid import uuid4
from .llm import TASK,SELECTION,CONTINUE,MESSAGE,RECOMMENDATIONS
from .contracts import validate_task,validate_selection,selected_cells,associate,evaluate_condition,AmbiguousSize
from .advice import ranked_cells,suggestion_catalog,validate_recommendations
from .inspection import observation_gallery
from .spatial import spatial_evidence,nearest,AmbiguousNearest,measurement
from .planning import HOME,SPEED,make_home_plan,make_plan,make_move_plan
from .observation import stationary_view,candidates,synthetic_scene,point
from .verification import compare

WINDOW=dict(stable_seconds=2.,tolerance_mm=3.,timeout_seconds=15.)
TERMINAL={'completed','failed','cancelled','observed','rejected','stopped'}
LIMITS=dict(max_targets=20,max_seconds=1800,passes_per_target=1,home=HOME,
            travel_z_mm=100,contact_z_mm=14.5,radius_mm=10,speed_mm_s=SPEED,
            initial_inventory_only=True)


class StopTask(Exception): pass


class Workflow:
    def __init__(self,tools,agents,directory,demo=False):
        self.tools,self.agents,self.directory,self.demo=tools,agents,Path(directory),demo
        self.runs={};self.lock=threading.RLock();self.active=None

    def update(self,rid,**data):
        with self.lock: self.runs[rid].update(data)

    def event(self,rid,role,message):
        with self.lock:
            self.runs[rid]['events'].append(dict(agent=role,message=message,time=datetime.now(timezone.utc).isoformat()))

    def new(self,prompt,chat_id=None,previous_run_ids=None):
        if chat_id is not None and (not isinstance(chat_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',chat_id)):
            raise ValueError('Invalid chat ID')
        previous_run_ids=previous_run_ids or []
        if not isinstance(previous_run_ids,list) or len(previous_run_ids)>8 or any(not isinstance(i,str) or not re.fullmatch(r'[a-f0-9]{32}',i) for i in previous_run_ids):
            raise ValueError('Invalid conversation run references')
        with self.lock:
            if self.active is not None: raise ValueError('Finish or cancel the current run first.')
            rid=uuid4().hex
            self.runs[rid]=dict(run_id=rid,state='preparing',events=[],prompt=prompt,task=None,
                simulated=self.tools.mode=='mock',synthetic_target=self.demo,motion_sent=False,
                audit=[],results=[],queue=[],attempted=[],stop_requested=False,limits=copy.deepcopy(LIMITS),
                chat_id=chat_id or uuid4().hex,previous_run_ids=previous_run_ids)
            self.active=rid
            return rid

    def get(self,rid):
        with self.lock:
            if rid not in self.runs: raise ValueError('Unknown run')
            return copy.deepcopy(self.runs[rid])

    def conversation(self,rid):
        """Only server-saved facts from this chat; browser-supplied measurements are never trusted."""
        r=self.get(rid);records={}
        for prior in r.get('previous_run_ids',[]):
            try:
                p=self.directory/(prior+'.json')
                if p.stat().st_size>5_000_000:continue
                data=json.loads(p.read_text())
                if data.get('run_id')==prior and data.get('chat_id')==r['chat_id']:records[prior]=data
            except (OSError,ValueError):pass
        for key,data in self.runs.items():
            if key!=rid and data.get('chat_id')==r['chat_id'] and data['state'] in TERMINAL:
                records[key]=data
        return [dict(run_id=v['run_id'],user_request=v['prompt'],answer=v.get('answer_message'),
                     task=v.get('task'),selected_targets=v.get('selected_targets',[]),
                     observation_frame_id=(v.get('observation') or {}).get('frame_id')) for v in list(records.values())[-8:]]

    async def cell_scene(self,rid):
        scene=synthetic_scene(1) if self.demo else await self.fresh_live(rid)
        self.update(rid,observation_calibration_id=scene['calibration']['calibration_id'])
        return await self.view(rid,lambda cells:cells)

    def previous_target(self,rid):
        for turn in reversed(self.conversation(rid)):
            selected=turn['selected_targets']
            if len(selected)>1:raise ValueError('The previous selection contains several cells. Specify which cell.')
            if len(selected)==1:return selected[0]
        raise ValueError('There is no selected cell in this chat. First find a cell or specify a target.')

    async def prepare_cell_move(self,rid,start):
        r=self.get(rid);task=r['task']
        try:
            previous=self.previous_target(rid) if task.get('use_previous_target') else None
            try:view=await self.cell_scene(rid)
            except ValueError:
                if await self.offer_home_observation(rid):return
                raise
            if previous:
                old_cal=previous.get('calibration_id')
                if old_cal and old_cal!=view['calibration_id']:raise ValueError('Target calibration changed; find the cell again.')
                target=associate(previous,view['cells'])
            else:
                inventory=copy.deepcopy(view['cells'])
                for cell in inventory:cell['target_id']=uuid4().hex
                distances=spatial_evidence(inventory,task,view['frame_id'])
                proposal=await self.decide(rid,'selection',dict(task=task,inventory=inventory,distances=distances),SELECTION)
                if proposal['action']=='ask':self.question(rid,proposal['message'],'recognition');return
                target=validate_selection(proposal,inventory,task)[0]
            target=dict(target,frame_id=view['frame_id'],calibration_id=view['calibration_id'])
            self.update(rid,move_target=target,selected_targets=[target])
            xy=target['printer_coordinates_mm']
            plan=make_move_plan(start,dict(x=xy['x'],y=xy['y'],z=100),'printer')
            await self.preview(rid,plan)
            if self.get(rid)['stop_requested']:self.finish(rid,'stopped');return
            self.update(rid,state='awaiting_confirmation',phase='cell_move',question=None)
            self.event(rid,'planner','Move above the measured cell at Z=100 mm; review and approve the displayed path. No cleaning.')
        except ValueError as exc:self.question(rid,str(exc),'recognition')

    def journal(self,rid,entry):
        entry=dict(time=datetime.now(timezone.utc).isoformat(),**entry)
        with self.lock:
            self.runs[rid]['audit'].append(entry)
            self.directory.mkdir(parents=True,exist_ok=True)
            with (self.directory/(rid+'.jsonl')).open('a') as out:
                out.write(json.dumps(entry,ensure_ascii=False)+'\n')

    def finish(self,rid,state,**data):
        self.update(rid,state=state,**data)
        self.journal(rid,dict(kind='terminal',state=state,data=data))
        with self.lock:
            if self.active==rid:self.active=None
        with (self.directory/(rid+'.json')).open('x') as out:
            json.dump(self.get(rid),out,indent=2,ensure_ascii=False)

    async def call(self,rid,server,name,args=None):
        self.journal(rid,dict(kind='tool_request',server=server,name=name,arguments=args or {}))
        try: result=await self.tools.call(server,name,args)
        except Exception as exc:
            self.journal(rid,dict(kind='tool_error',name=name,error=str(exc)));raise
        self.journal(rid,dict(kind='tool_result',name=name,result=result))
        return result

    async def decide(self,rid,role,evidence,contract):
        result=await self.agents.decide(role,evidence,contract)
        # Also validates scripted adapters; model format guarantees are not trusted.
        from jsonschema import validate
        validate(result,contract)
        self.journal(rid,dict(kind='llm_proposal',role=role,evidence=evidence,result=result))
        return result

    def question(self,rid,message,context):
        self.update(rid,state='awaiting_answer',question=message,question_context=context)
        self.event(rid,'coordinator',message)
        self.journal(rid,dict(kind='question',context=context,message=message))

    async def position(self,rid):
        reply=await self.call(rid,'printer','printer_command',{'request':{'command':'position'}})
        if reply.get('simulated')!=(self.tools.mode=='mock'): raise ValueError('Printer mode mismatch')
        return [reply['data']['position_mm'][a] for a in 'xyz']

    async def preview(self,rid,plan):
        speed=self.get(rid)['limits']['speed_mm_s']
        plan['speed_mm_s']=speed
        preview=(await self.call(rid,'printer','preview_sequence',dict(steps=plan['steps'],speed_mm_s=speed,z_speed_mm_s=speed))
                 if plan['steps'] else await self.call(rid,'printer','preview_position',dict(zip('xyz',plan['start']),speed_mm_s=speed)))
        if preview.get('simulated')!=(self.tools.mode=='mock') or any(abs(a-b)>.002 for a,b in zip(preview['start'],plan['start'])):
            raise ValueError('Printer changed during planning or mode mismatch')
        self.update(rid,plan=plan,preview=preview,preview_monotonic=time.monotonic())
        return preview

    async def inspect(self,rid):
        """Read-only status collection. Independent failures remain explicit evidence."""
        facts={'simulated_printer':self.tools.mode=='mock','synthetic_camera':self.demo}
        for key,server,name,args in (
            ('printer','printer','printer_status',None),
            ('position','printer','printer_command',{'request':{'command':'position'}}),
            ('camera','scanner','camera_get_status',None),
            ('source','scanner','camera_get_sources',None)):
            try: facts[key]={'available':True,'data':await self.call(rid,server,name,args)}
            except Exception as exc: facts[key]={'available':False,'error':str(exc)}
        scene=None
        task=self.get(rid)['task']
        try:
            # Measurements and displayed images must refer to the same saved frame.
            scene=synthetic_scene(1) if self.demo else await self.call(rid,'scanner','scanner_scan_current_frame')
            if (task.get('distance_between') or task.get('selection') or task.get('use_previous_target')) and not self.demo:
                self.validate_frame(scene,None,time.time()-2)
                self.update(rid,observation_calibration_id=scene['calibration']['calibration_id'])
                view=await self.view(rid,lambda cells:cells)
                scene=dict(view,detections=view['cells'])
            if self.demo:
                scene['frame']={'acquired_at':datetime.now(timezone.utc).isoformat()}
            timestamp=datetime.fromisoformat(scene['frame']['acquired_at']).timestamp()
            if not -1<=time.time()-timestamp<=2: raise ValueError('Stale camera frame; current counts unavailable')
            if ((scene.get('calibration') or {}).get('status')!='valid' or
                    (scene.get('calibration') or {}).get('detections_available') is False):
                raise ValueError('Board reference unavailable; cell count is unknown, not zero')
            facts['observation']={'available':True,'frame_id':scene['frame_id'],
                'acquired_at':scene['frame']['acquired_at'],'counts':{color:sum(c.get('color')==color for c in scene['detections']) for color in ('blue','green')},
                'calibration':scene.get('calibration'),
                'cells':[dict(detection_id=c.get('detection_id'),color=c.get('color'),area_mm2=c.get('area_mm2'),
                              printer_coordinates_mm=c.get('printer_coordinates_mm')) for c in scene['detections']]}
        except Exception as exc:
            facts['observation']={'available':False,'error':str(exc)}
            scene=None
        ranked=ranked_cells(facts['observation'])
        if task.get('selection') or task.get('use_previous_target'):
            if scene is None:
                if await self.offer_home_observation(rid):return
                self.question(rid,'A fresh calibrated view is required to identify the requested cell.','recognition');return
            try:
                inventory=copy.deepcopy(candidates(scene))
                for cell in inventory:cell['target_id']=uuid4().hex
                if task.get('use_previous_target'):
                    previous=self.previous_target(rid)
                    if previous.get('calibration_id') and previous['calibration_id']!=scene['calibration']['calibration_id']:
                        raise ValueError('Target calibration changed; find the cell again.')
                    chosen=[associate(previous,inventory)]
                    distances=[]
                else:
                    distances=spatial_evidence(inventory,task,scene['frame_id'])
                    proposal=await self.decide(rid,'selection',dict(task=task,inventory=inventory,distances=distances),SELECTION)
                    if proposal['action']=='ask':self.question(rid,proposal['message'],'recognition');return
                    chosen=validate_selection(proposal,inventory,task)
                chosen=[dict(c,frame_id=scene['frame_id'],calibration_id=scene['calibration']['calibration_id']) for c in chosen]
                self.update(rid,selected_targets=chosen,distances=distances)
                self.journal(rid,dict(kind='measured_selection',targets=chosen,distances=distances))
                facts['selected_targets']=chosen
                if distances:
                    facts['distances']=[d for d in distances if d['to_target_id'] in {c['target_id'] for c in chosen}]
                    self.update(rid,distances=facts['distances'])
                    scene['distance_measurements']=facts['distances']
            except ValueError as exc:self.question(rid,str(exc),'recognition');return
        if scene is None and task.get('observe_from_home'):
            self.question(rid,'Վստահելի պատկեր դեռ չկա։ Ստուգիր կամերան և տախտակի կալիբրացիան։ '+facts['observation']['error'],'recognition');return
        if task.get('distance_between'):
            if scene is None:
                if await self.offer_home_observation(rid): return
                self.question(rid,'Տանից էլ վստահելի պատկեր չի ստացվել։ Ստուգիր կամերան և կալիբրացիան։ '+facts['observation']['error'],'recognition');return
            try:
                inventory=copy.deepcopy(candidates(scene))
                for cell in inventory: cell['target_id']=uuid4().hex
                self.journal(rid,dict(kind='tool_request',name='measure_cell_distances',arguments=dict(task=task,inventory=inventory,frame_id=scene['frame_id'])))
                distances=spatial_evidence(inventory,task,scene['frame_id'])
                self.journal(rid,dict(kind='tool_result',name='measure_cell_distances',result=distances))
                proposal=await self.decide(rid,'selection',dict(task=task,inventory=inventory,distances=distances,
                    instruction='Return the two measured endpoint IDs in requested order; ask if ambiguous.'),SELECTION)
                if proposal['action']=='ask': self.question(rid,proposal['message'],'recognition');return
                if proposal['target_ids'] != [distances[0]['from_target_id'],distances[0]['to_target_id']]:
                    raise ValueError('Distance endpoint IDs do not match the measured selectors')
                facts['distances']=distances
                self.update(rid,distances=distances)
                scene['distance_measurements']=distances
            except ValueError as exc:
                self.question(rid,str(exc),'recognition');return
        facts['ranked_cells']=ranked
        self.update(rid,status_evidence=facts)
        try:
            answer=await self.decide(rid,'status_answer',dict(user_request=self.get(rid)['prompt'],evidence=facts,conversation=self.conversation(rid)),MESSAGE)
        except Exception as exc:
            from .status import measured_summary
            self.journal(rid,dict(kind='status_answer_unavailable',error=str(exc)))
            self.update(rid,answer_warning=str(exc))
            answer={'message':measured_summary(facts)}
        if facts.get('distances'):
            d=facts['distances'][0]
            answer['message']+=f"\nXY կենտրոնների հեռավորությունը՝ {d['distance_mm']:.2f} մմ։"
        catalog=suggestion_catalog(facts,ranked,english=not any('\u0531'<=ch<='\u058f' for ch in self.get(rid)['prompt']))
        try:
            proposal=await self.decide(rid,'recommendations',dict(user_request=self.get(rid)['prompt'],
                evidence=facts,catalog=catalog),RECOMMENDATIONS)
            suggestions=validate_recommendations(proposal,catalog)
            suggestion_reason=proposal['message']
        except Exception as exc:
            self.journal(rid,dict(kind='recommendations_unavailable',error=str(exc)))
            suggestions=catalog[:2]
            suggestion_reason='Առաջարկները հիմնված են ընթացիկ չափումների վրա։'
        gallery=None;image_warning=None
        if scene is not None and not self.demo:
            try:
                gallery=await observation_gallery(scene,ranked,self.directory)
                if gallery['frame_id']!=scene['frame_id']:raise ValueError('Observation image frame changed')
                by_id={cell['detection_id']:cell for cell in gallery['cells']}
                ranked=[dict(cell,**dict(image_index=by_id[cell['detection_id']]['index'],
                    display_number=by_id[cell['detection_id']]['display_number']))
                    if cell['detection_id'] in by_id else cell for cell in ranked]
                self.journal(rid,dict(kind='observation_images',gallery=gallery))
            except Exception as exc:
                gallery=None;image_warning=str(exc)
                self.journal(rid,dict(kind='observation_images_unavailable',error=image_warning))
        self.event(rid,'coordinator',answer['message'])
        self.finish(rid,'observed',observation=scene,status_evidence=facts,answer_message=answer['message'],
                    ranked_cells=ranked,suggestions=suggestions,suggestion_reason=suggestion_reason,
                    observation_images=gallery,observation_image_warning=image_warning)

    async def offer_home_observation(self,rid):
        """Prepare a separate approved home leg, at most once; never auto-dispatch."""
        r=self.get(rid)
        if r.get('home_observation_attempted'): return False
        status=await self.call(rid,'printer','printer_status')
        if status.get('state',{}).get('webhooks',{}).get('state')!='ready': return False
        start=await self.position(rid)
        if all(abs(a-b)<=.002 for a,b in zip(start,HOME)): return False
        await self.preview(rid,make_home_plan(start))
        if self.get(rid)['stop_requested']:
            self.finish(rid,'stopped');return True
        self.update(rid,state='awaiting_confirmation',phase='observe_home',authorization=None,question=None)
        self.event(rid,'planner','Տանից նորից դիտելու համար հաստատիր ցուցադրված տուն գնալու ճանապարհը։ Այս քայլը մաքրում չի կատարում։')
        return True

    async def fresh_live(self,rid,timeout=5):
        """Wait for the next fresh result, without relaxing age/calibration checks."""
        deadline=time.monotonic()+timeout
        while True:
            scene=await self.call(rid,'scanner','scanner_get_live_detections')
            try:
                self.validate_frame(scene,None,time.time()-2)
                return scene
            except ValueError as exc:
                if str(exc)!='Stale camera frame' or time.monotonic()>=deadline:
                    raise
            await asyncio.sleep(.15)

    async def prepare(self,rid):
        try:
            r=self.get(rid)
            evidence=dict(user_request=r['prompt'], conversation=self.conversation(rid))
            if r.get('answer'): evidence.update(previous_task=r.get('task'),user_answer=r['answer'])
            task=validate_task(await self.decide(rid,'coordinator',evidence,TASK))
            if task['action'] in ('wipe','move','home'):
                if re.search(r'(?i)\bif\b|եթե',r['prompt']) and task.get('condition') is None:
                    self.question(rid,'Պայմանը հստակ չհասկացա։ Նշիր՝ ինչ չափված քանակ կամ մակերեսի շեմով որոշեմ գործողությունը։','intent');return
                if re.search(r'(?i)\belse\b|\botherwise\b|հակառակ դեպքում|այլապես',r['prompt']):
                    self.question(rid,'Այլ ճյուղով շարժում այս փուլում չի աջակցվում։ Գրիր մեկ պայման և մեկ գործողություն․ չկատարվելու դեպքում կզեկուցեմ ու կավարտեմ։','intent');return
            limits=copy.deepcopy(LIMITS)
            limits['speed_mm_s']=task.get('speed_mm_s') or SPEED
            self.update(rid,task=task,coordinator_decision=task,limits=limits)
            self.event(rid,'coordinator',task['message'])
            if task['action']=='ask': self.question(rid,task['message'],'intent');return
            if task['action']=='reject': self.finish(rid,'rejected');return
            if task['action']=='inspect':
                if task.get('observe_from_home') and await self.offer_home_observation(rid): return
                await self.inspect(rid);return
            status=await self.call(rid,'printer','printer_status')
            if status.get('state',{}).get('webhooks',{}).get('state')!='ready':
                raise ValueError('Printer not ready: '+str(status.get('state',{}).get('webhooks',{}).get('state_message') or status.get('state',{}).get('webhooks',{}).get('state','unknown'))+
                    (' · Վերականգնել սիմուլյացիան, հետո նորից փորձել։' if self.tools.mode=='mock' else ' · Check the printer controller; recovery is manual.'))
            start=await self.position(rid)
            if task['action']=='move' and ((task.get('coordinates') is None and task.get('selection')) or task.get('use_previous_target')):
                await self.prepare_cell_move(rid,start);return
            if task.get('condition') is not None:
                if any(abs(a-b)>.05 for a,b in zip(start,HOME)):
                    self.question(rid,'Պայմանը ստուգելու համար նախ առանձին հրահանգով գնա տուն, ապա կրկնիր պայմանական առաջադրանքը։ Այժմ շարժում չի ուղարկվել։','intent')
                    return
                try:
                    scene=synthetic_scene(1) if self.demo else await self.fresh_live(rid)
                    calibration=scene['calibration']['calibration_id']
                    view=await stationary_view(self.tools,WINDOW,calibration,after=time.time(),
                        demo_index=1 if self.demo else None,selector=lambda cells:cells)
                    measured=candidates(dict(detections=view['cells']))
                    result=evaluate_condition(task['condition'],measured)
                except Exception as exc:
                    self.question(rid,'Պայմանը վստահելի չափումներով չստուգվեց․ '+str(exc),'intent');return
                self.update(rid,condition_result=result,condition_frame_ids=view['frame_ids'])
                self.journal(rid,dict(kind='condition_evaluation',result=result,frame_ids=view['frame_ids']))
                if not result['passed']:
                    message=f"Պայմանը չի կատարվում․ չափված արժեքները {result['left']:.2f} և {result['right']:.2f} են։ Շարժում չի կատարվել։"
                    self.finish(rid,'observed',answer_message=message,condition_result=result);return
            if task['action']=='wipe':
                vision=await self.agents.check_vision()
                self.journal(rid,dict(kind='vision_preflight',result=vision))
                # The head can hide the board border away from the observation
                # position. Establish calibration only after arriving home.
                self.update(rid,stability=WINDOW.copy(),vision_preflight=vision)
            plan=make_home_plan(start) if task['action'] in ('wipe','home') else make_move_plan(start,task['coordinates'],task['coordinate_system'])
            if task['action']=='home': plan['destination']=HOME[:]
            if task['action']=='wipe' and not plan['steps']:
                await self.recognize(rid)
                return
            await self.preview(rid,plan)
            if self.get(rid)['stop_requested']:
                self.finish(rid,'stopped');return
            self.update(rid,state='awaiting_confirmation',phase='home' if task['action']=='wipe' else 'task',question=None)
            self.event(rid,'planner','Հաստատիր միայն ցուցադրված ճանապարհը։ Մաքրումը պահանջում է առանձին հաստատում։')
        except Exception as exc: self.finish(rid,'failed',error=str(exc))

    def approve(self,rid,confirmed,clear_path):
        with self.lock:
            r=self.runs[rid]
            if r['state']!='awaiting_confirmation': raise ValueError('No pending task authorization')
            if confirmed is not True or clear_path is not True: raise ValueError('Confirm the task scope and full swept footprint')
            if time.monotonic()-r['preview_monotonic']>110: raise ValueError('Preview expired; prepare a new task')
            if self.tools.mode=='real' and (self.demo or os.getenv('PRINTER_ALLOW_MOTION')!='1'):
                raise ValueError('Real motion is disabled')
            if r.get('stop_requested'): raise ValueError('Task was stopped')
            r.update(state='executing',authorization=dict(task=copy.deepcopy(r['task']),limits=copy.deepcopy(r['limits']),
                         created=time.monotonic(),id=uuid4().hex,plan=copy.deepcopy(r['plan']),phase=r['phase'],
                         batch_paths=copy.deepcopy(r.get('batch_paths')) if r['phase']=='wipe' else None,
                         batch_targets=copy.deepcopy(r['queue']) if r.get('batch_paths') and r['phase']=='wipe' else None))
            self.journal(rid,dict(kind='operator_authorization',authorization=r['authorization']))

    def guard(self,rid):
        r=self.get(rid)
        if r.get('stop_requested'): raise StopTask('Task stopped; no next target started')
        auth=r.get('authorization')
        if not auth or auth['task']!=r['task'] or auth['limits']!=r['limits'] or r['limits']!=dict(LIMITS,speed_mm_s=r['task'].get('speed_mm_s') or SPEED):
            raise ValueError('No matching task authorization')
        if auth.get('batch_paths') and auth['batch_targets']!=r['queue']:
            raise ValueError('Approved batch targets changed')
        if time.monotonic()-auth['created']>LIMITS['max_seconds']: raise ValueError('Task authorization expired')
        if self.tools.mode=='real' and (self.demo or os.getenv('PRINTER_ALLOW_MOTION')!='1'):
            raise ValueError('Real motion is disabled')

    async def dispatch(self,rid,plan,preview):
        self.guard(rid)
        auth=self.get(rid)['authorization']
        approved=(auth['batch_paths'].get(self.get(rid).get('current_target_id'))
                  if auth.get('batch_paths') else auth['plan'])
        if approved != plan:
            raise ValueError('Path differs from the operator-approved plan')
        if time.monotonic()-self.get(rid)['preview_monotonic']>110: raise ValueError('Path preview expired')
        self.update(rid,motion_sent=self.tools.mode=='real' or self.get(rid)['motion_sent'])
        reply=await self.call(rid,'printer','execute_sequence',dict(token=preview['token'],operator_confirmed=True))
        if not reply.get('ok'): raise RuntimeError('Uncertain movement; never automatically retry')
        actual=await self.position(rid)
        expected=plan['waypoints'][-1] if plan['waypoints'] else plan['start']
        if any(abs(a-b)>.002 for a,b in zip(actual,expected)): raise RuntimeError('Reported destination differs; do not retry')
        return reply,actual

    def validate_frame(self,scene,calibration_id,after):
        cal=scene.get('calibration') or {}
        if cal.get('status')!='valid': raise ValueError('Fresh valid board calibration required')
        if calibration_id and cal.get('calibration_id')!=calibration_id: raise ValueError('Calibration changed')
        timestamp=datetime.fromisoformat(scene['frame']['acquired_at']).timestamp()
        if timestamp<after or not -1<=time.time()-timestamp<=2: raise ValueError('Stale camera frame')

    async def view(self,rid,selector):
        r=self.get(rid)
        result=await stationary_view(self.tools,WINDOW,r['observation_calibration_id'],after=time.time(),
                                     demo_index=1 if self.demo else None,selector=selector)
        self.journal(rid,dict(kind='stationary_view',result=result))
        return result

    async def fresh_saved(self,rid):
        # Post-return camera frame must be newer than settling, not a cached pre-motion image.
        await asyncio.sleep(.5)
        r=self.get(rid);after=time.time()
        scene=await self.call(rid,'scanner','scanner_scan_current_frame')
        self.validate_frame(scene,r['observation_calibration_id'],after)
        return dict(frame_id=scene['frame_id'],calibration=scene['calibration'],frame=scene['frame'],
                    raw_image=scene['frame']['raw_image'],annotated_image=scene.get('annotated_image'),cells=candidates(scene))

    async def execute(self,rid):
        try:
            r=self.get(rid)
            if r['state']!='executing': raise ValueError('Task not authorized for execution')
            self.guard(rid)
            if r['phase']=='wipe':
                await self.process_queue(rid)
                return
            if r['phase']=='cell_move' and not self.demo:
                scene=await self.fresh_live(rid)
                self.validate_frame(scene,r['observation_calibration_id'],time.time()-2)
                associate(r['move_target'],candidates(scene))
            reply,actual=await self.dispatch(rid,r['plan'],r['preview'])
            if r['phase']=='observe_home':
                self.update(rid,home_execution=reply,authorization=None,home_observation_attempted=True,phase='inspection')
                if not self.demo: await asyncio.sleep(.5)
                if r['task']['action']=='move':await self.prepare_cell_move(rid,actual)
                else:await self.inspect(rid)
                return
            if r['task']['action'] in ('move','home'):
                self.finish(rid,'completed',verification=dict(position_mm=dict(zip('xyz',actual)),move_completed=True));return
            self.update(rid,home_execution=reply,authorization=None,phase='recognition')
            if not self.demo: await asyncio.sleep(.5)
            await self.recognize(rid)
        except StopTask as exc: self.finish(rid,'stopped',message=str(exc))
        except Exception as exc: self.finish(rid,'failed',error=str(exc))

    async def recognize(self,rid):
        r=self.get(rid)
        try:
            scene=synthetic_scene(1) if self.demo else await self.fresh_live(rid)
            calibration=scene['calibration']['calibration_id']
            self.update(rid,observation_calibration_id=calibration)
            # Stabilize positions before ranking sizes. A ranking tie is a choice,
            # not a camera stability failure to poll until timeout.
            view=await self.view(rid,lambda cells:[c for c in cells if c['color'] in (r['task']['color'],r['task']['reference']['color'])] if r['task'].get('selection')=='nearest' else [c for c in cells if c['color']==r['task']['color']])
        except ValueError as exc: self.question(rid,str(exc),'recognition');return
        inventory=copy.deepcopy(view['cells'])
        for cell in inventory: cell['target_id']=uuid4().hex
        self.update(rid,inventory=inventory,observation_view=view)
        if r['task'].get('selection') in ('smallest','largest'):
            try: selected_cells(inventory,r['task'])
            except AmbiguousSize as exc:
                options=exc.options;gallery=None;warning=None
                if not self.demo:
                    try:
                        gallery=await observation_gallery(dict(view,detections=inventory),options,self.directory)
                        if gallery['frame_id']!=view['frame_id']:raise ValueError('Observation image frame changed')
                        images={c['detection_id']:c for c in gallery['cells']}
                        options=[dict(c,image_index=images[c['detection_id']]['index'],display_number=images[c['detection_id']]['display_number']) if c['detection_id'] in images else c for c in options]
                    except Exception as image_error:
                        gallery=None;warning=str(image_error)
                self.update(rid,size_options=options,ranked_cells=options,observation_images=gallery,observation_image_warning=warning)
                details='\n'.join(f"{i+1}. {c['area_mm2']:.1f} մմ² · X={c['printer_coordinates_mm']['x']:.1f}, Y={c['printer_coordinates_mm']['y']:.1f} մմ" for i,c in enumerate(options))
                self.question(rid,'Բջիջների չափերը շատ մոտ են (մինչև 5%)։ Ո՞րն ընտրեմ։ Գրիր տարբերակի համարը՝ 1, 2 և այլն։\n'+details,'size_choice');return
        try:
            self.journal(rid,dict(kind='tool_request',name='measure_cell_distances',arguments=dict(task=r['task'],inventory=inventory,frame_id=view['frame_id'])))
            distances=spatial_evidence(inventory,r['task'],view['frame_id'])
        except AmbiguousNearest as exc:
            distances=[measurement(exc.reference,c,view['frame_id']) for c in exc.options]
            self.update(rid,spatial_options=exc.options,spatial_reference=exc.reference,distances=distances)
            self.journal(rid,dict(kind='tool_result',name='measure_cell_distances',result=distances))
            self.question(rid,str(exc),'spatial_choice');return
        except ValueError as exc:
            self.question(rid,str(exc),'recognition');return
        if distances:
            self.update(rid,distances=distances)
            self.journal(rid,dict(kind='tool_result',name='measure_cell_distances',result=distances))
        proposal=await self.decide(rid,'selection',dict(task=r['task'],inventory=inventory,distances=distances),SELECTION)
        if proposal['action']=='ask': self.question(rid,proposal['message'],'recognition');return
        chosen=validate_selection(proposal,inventory,r['task'])
        if len(chosen)>LIMITS['max_targets']: raise ValueError('Too many targets (maximum 20)')
        self.update(rid,queue=chosen,phase='wipe',queue_index=0)
        await self.process_queue(rid)

    async def prepare_batch_paths(self,rid,first_target,first_plan,first_preview):
        """Validate every fixed path before asking for one bounded batch approval."""
        r=self.get(rid)
        paths={};segments=[];waypoints=[];steps=[]
        for cell in r['queue'][r.get('queue_index',0):]:
            tid=cell['target_id']
            plan=copy.deepcopy(first_plan) if tid==first_target['target_id'] else make_plan(HOME,cell['printer_coordinates_mm'])
            plan['speed_mm_s']=r['limits']['speed_mm_s']
            if tid!=first_target['target_id']:
                checked=await self.call(rid,'printer','preview_sequence',dict(steps=plan['steps'],
                    speed_mm_s=r['limits']['speed_mm_s'],z_speed_mm_s=r['limits']['speed_mm_s']))
                if checked.get('simulated')!=(self.tools.mode=='mock') or any(abs(a-b)>.002 for a,b in zip(checked['start'],HOME)):
                    raise ValueError('Printer changed while validating batch paths')
            paths[tid]=plan
            segments.append(dict(target_id=tid,target=plan['target'],first_waypoint=len(waypoints)+1,
                                 last_waypoint=len(waypoints)+len(plan['waypoints'])))
            waypoints.extend(copy.deepcopy(plan['waypoints']));steps.extend(copy.deepcopy(plan['steps']))
        combined=dict(kind='batch_wipe',start=first_plan['start'],home=HOME[:],waypoints=waypoints,steps=steps,
            speed_mm_s=r['limits']['speed_mm_s'],segments=segments,target_count=len(paths),
            note='One approval covers only these displayed fixed paths, one pass per initial target. Residue is reported at the end; no automatic repeat.')
        self.update(rid,batch_paths=paths,approved_batch_plan=combined,plan=combined,preview=first_preview)
        self.journal(rid,dict(kind='batch_paths_prepared',plan=combined,paths=paths))

    def completed_summary(self,rid):
        r=self.get(rid);results=r['results']
        counts={key:sum(item.get('verdict')==key for item in results) for key in ('clean','residue','uncertain','skipped')}
        return (f"Առաջադրանքի մաքրման փորձերն ավարտված են՝ {len(r['attempted'])}/{len(r['queue'])} բջիջ։ "
                f"Մաքուր՝ {counts['clean']}, մնացորդով՝ {counts['residue']}, "
                f"անորոշ՝ {counts['uncertain']}, բաց թողնված՝ {counts['skipped']}։ "
                "Յուրաքանչյուր բջջի համար կատարվել է առավելագույնը մեկ շրջան։")

    async def process_queue(self,rid):
        r=self.get(rid)
        for index in range(r.get('queue_index',0),len(r['queue'])):
            if self.get(rid)['stop_requested']: raise StopTask('Task stopped')
            target=copy.deepcopy(r['queue'][index]);tid=target['target_id']
            self.update(rid,queue_index=index,current_target_id=tid,state='executing',phase='wipe')
            if tid in self.get(rid)['attempted']: raise ValueError('Target already attempted; new task required to repeat')
            pending=self.get(rid).get('pending_wipe')
            if pending is None:
                try:
                    before=await self.view(rid,lambda cells:[associate(target,cells,WINDOW['tolerance_mm'])])
                    measured=associate(target,before['cells'],WINDOW['tolerance_mm'])
                except ValueError as exc: self.question(rid,str(exc),'target');return
                target.update(measured);target['target_id']=tid
                target.update(frame_id=before['frame_id'],annotated_image=before.get('annotated_image'))
                self.update(rid,target=target)
                # Ensure usable ROI/evidence BEFORE physical wiping, including board-edge coverage.
                if not self.demo:
                    initial_evidence=await compare(before,before,target,self.directory)
                    if not initial_evidence['evidence_usable']:
                        self.question(rid,'Target image is obscured or has insufficient measurable ink.','target');return
                start=await self.position(rid)
                if any(abs(a-b)>.002 for a,b in zip(start,HOME)): raise ValueError('Expected home before each target')
                batch_auth=(self.get(rid).get('authorization') or {}).get('batch_paths')
                if batch_auth:
                    self.guard(rid)
                    plan=copy.deepcopy(batch_auth[tid])
                else:
                    plan=make_plan(start,target['printer_coordinates_mm'])
                preview=await self.preview(rid,plan)
                pending=dict(target=target,before=before,plan=plan,preview=preview)
                if batch_auth:
                    # A new token validates the exact path already reviewed for this target.
                    self.update(rid,pending_wipe=pending,question=None)
                else:
                    if r['task'].get('selection')=='all':
                        await self.prepare_batch_paths(rid,target,plan,preview)
                    self.update(rid,pending_wipe=pending,authorization=None,state='awaiting_confirmation',phase='wipe',question=None)
                    self.event(rid,'planner',
                        'Բոլոր ընտրված բջիջների ճանապարհները պատրաստ են։ Հաստատումից հետո կմշակեմ հերթով, մեկական շրջանով, և վերջում կամփոփեմ արդյունքները։'
                        if r['task'].get('selection')=='all' else 'Թիրախը ճանաչված է, ամբողջ ճանապարհը պատրաստ է։ Հաստատե՞լ մաքրումը։')
                    return
            target,before,plan,preview=(pending[k] for k in ('target','before','plan','preview'))
            if target['target_id']!=tid: raise ValueError('Pending target changed')
            if not self.demo:
                scene=await self.call(rid,'scanner','scanner_get_live_detections')
                self.validate_frame(scene,r['observation_calibration_id'],time.time()-2)
                reference=dict(target,printer_coordinates_mm=dict(zip(('x','y'),plan['target'])))
                associate(reference,candidates(scene),WINDOW['tolerance_mm'])
            self.guard(rid)
            self.update(rid,attempted=self.get(rid)['attempted']+[tid],pending_wipe=None)
            self.event(rid,'executor',f'Մաքրում՝ {index+1}/{len(r["queue"])} · {target["color"]}')
            reply,actual=await self.dispatch(rid,plan,preview)
            record=dict(target_id=tid,target=target,execution=reply,plan=plan,before_frame_id=before['frame_id'],
                        synthetic=self.demo,simulated_printer=self.tools.mode=='mock',
                        verdict='uncertain',physical_contact_verified=False)
            # Record execution before any verifier that could fail.
            self.update(rid,results=self.get(rid)['results']+[record],queue_index=index+1,
                        verification=dict(returned_home=True,position_mm=dict(zip('xyz',actual))))
            try:
                if self.demo:
                    evidence=dict(synthetic=True,remaining_fraction=0,evidence_usable=True)
                else:
                    after=await self.fresh_saved(rid)
                    evidence=await compare(before,after,target,self.directory)
                # Preserve measured evidence even when the external assessor fails.
                record['evidence']=evidence
                assessment=await self.agents.assess(evidence,evidence.get('images',[]))
                from jsonschema import validate
                from .llm import ASSESSMENT
                validate(assessment,ASSESSMENT)
                # A model cannot certify missing/occluded evidence or substantial measured ink.
                if not evidence.get('evidence_usable') or evidence.get('remaining_fraction') is None:
                    assessment=dict(verdict='uncertain',message='Evidence quality is insufficient')
                elif assessment['verdict']=='clean' and evidence['remaining_fraction']>.10:
                    assessment=dict(verdict='residue',message='More than 10% colored ink remains in the ROI')
                if self.tools.mode=='mock' and not self.demo:
                    assessment=dict(verdict='uncertain',message='Simulated motion cannot establish physical cleaning')
                record.update(evidence=evidence,assessment=assessment,verdict=assessment['verdict'])
                self.journal(rid,dict(kind='visual_assessment',result=record))
            except Exception as exc:
                record.update(assessment=dict(verdict='uncertain',message=str(exc)))
                self.journal(rid,dict(kind='visual_assessment_unavailable',result=record))
            results=self.get(rid)['results'];results[-1]=record;self.update(rid,results=results)
            self.event(rid,'verifier',record['assessment']['message'])
            self.guard(rid)
            batch=(self.get(rid).get('authorization') or {}).get('batch_paths')
            measured=record.get('evidence') or {}
            fraction=measured.get('remaining_fraction')
            usable=(measured.get('evidence_usable') is True and
                    isinstance(fraction,(int,float)) and not isinstance(fraction,bool) and
                    math.isfinite(fraction) and fraction>=0)
            if record['verdict']!='clean' and not (batch and usable):
                self.question(rid,'Մնացորդ կա կամ արդյունքն անորոշ է։ Շարունակե՞լ մնացած թիրախները, թե ավարտել։ Այս բջիջը ինքնաբերաբար չի կրկնվի։','verification');return
        self.finish(rid,'completed',summary=self.completed_summary(rid))

    def claim_answer(self,rid,answer):
        if not isinstance(answer,str) or not answer.strip() or len(answer)>2000: raise ValueError('Provide a short answer')
        with self.lock:
            if self.runs[rid]['state']!='awaiting_answer': raise ValueError('No pending question')
            self.runs[rid].update(state='answering',answer=answer)

    async def answer(self,rid):
        try:
            r=self.get(rid)
            self.journal(rid,dict(kind='user_answer',text=r['answer']))
            if r['question_context']=='size_choice':
                options=r['size_options'];answer=r['answer'].strip()
                if not answer.isdecimal() or not 1<=int(answer)<=len(options):
                    self.question(rid,'Գրիր ցուցադրված տարբերակի համարը՝ 1-ից '+str(len(options))+'։','size_choice');return
                chosen=options[int(answer)-1]
                await self.view(rid,lambda cells:[associate(chosen,cells)])
                self.update(rid,queue=[chosen],queue_index=0,phase='wipe',authorization=None,question=None)
                self.journal(rid,dict(kind='operator_target_choice',target_id=chosen['target_id'],answer=answer))
                await self.process_queue(rid);return
            if r['question_context']=='spatial_choice':
                proposal=await self.decide(rid,'selection',dict(task=r['task'],user_answer=r['answer'],
                    inventory=r['spatial_options'],distances=r['distances'],
                    instruction='The operator is resolving a nearest-distance tie. Options are in numbered order. Select exactly one offered ID only if their answer identifies it clearly; otherwise ask.'),SELECTION)
                if proposal['action']=='ask':self.question(rid,proposal['message'],'spatial_choice');return
                ids=proposal['target_ids'];by_id={c['target_id']:c for c in r['spatial_options']}
                if len(ids)!=1 or ids[0] not in by_id:raise ValueError('Clarification selected an unoffered target')
                chosen=by_id[ids[0]]
                # Re-observe both endpoints before preparing the chosen exact path.
                await self.view(rid,lambda cells:[associate(r['spatial_reference'],cells),associate(chosen,cells)])
                self.update(rid,queue=[chosen],queue_index=0,phase='wipe',authorization=None,question=None)
                self.journal(rid,dict(kind='operator_target_choice',target_id=ids[0],answer=r['answer']))
                await self.process_queue(rid);return
            if r['question_context'] in ('intent','recognition'):
                # Revised intent always needs a new explicit approval, same run/history.
                self.update(rid,authorization=None,pending_wipe=None,state='preparing',question=None)
                await self.prepare(rid);return
            reply=await self.decide(rid,'continuation',dict(task=r['task'],user_answer=r['answer'],
                question=r['question'],remaining=r['queue'][r['queue_index']:],
                instruction='Continue skips the current problem cell. Retry or scope change requires a new task.'),CONTINUE)
            if reply['action']=='ask': self.question(rid,reply['message'],r['question_context']);return
            if reply['action']=='finish': self.finish(rid,'stopped',message=reply['message']);return
            if self.get(rid)['stop_requested']: raise StopTask('Task stopped')
            if r['question_context']=='target':
                skipped=r['queue'][r['queue_index']]
                self.update(rid,queue_index=r['queue_index']+1,results=r['results']+[dict(target_id=skipped['target_id'],verdict='skipped')])
            self.update(rid,state='executing',question=None)
            await self.process_queue(rid)
        except StopTask as exc: self.finish(rid,'stopped',message=str(exc))
        except Exception as exc: self.finish(rid,'failed',error=str(exc))

    def request_stop(self,rid):
        with self.lock:
            r=self.runs[rid]
            if r['state'] in TERMINAL: raise ValueError('Run already finished')
            r['stop_requested']=True
            if r['state'] in ('awaiting_answer','awaiting_confirmation'):
                self.finish(rid,'stopped')
            else: self.event(rid,'system','Կանգ՝ ընթացիկ ուղու ավարտից հետո։ Նոր թիրախ չի սկսվի։')

    def cancel(self,rid):
        with self.lock:
            if self.runs[rid]['state'] not in ('awaiting_confirmation','awaiting_answer'): raise ValueError('Use stop-task during execution')
            self.finish(rid,'cancelled')
