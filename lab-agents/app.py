"""Local agent dashboard. Defaults to simulated printer with the live scanner."""
import argparse
import asyncio
import atexit
from pathlib import Path
import os
import threading
from flask import Flask, jsonify, request, send_file, render_template
from dotenv import load_dotenv
from agents.llm import GroqAgents
from agents.tools import Tools
from agents.workflow import Workflow
from agents.planning import HOME
from remote_access import install_remote_access,remote_password,is_loopback

ROOT=Path(__file__).resolve().parent


class Runtime:
    def __init__(self,mode,demo):
        self.loop=asyncio.new_event_loop()
        self.thread=threading.Thread(target=self.loop.run_forever,daemon=True)
        self.thread.start()
        self.tools=Tools(mode)
        self.submit(self.tools.open()).result(timeout=30)
        self.workflow=Workflow(self.tools,GroqAgents(demo),ROOT/'results',demo)

    def submit(self,coro): return asyncio.run_coroutine_threadsafe(coro,self.loop)

    async def reset_mock(self):
        flow=self.workflow
        with flow.lock:
            if self.tools.mode!='mock': raise ValueError('Reset is available only in simulation.')
            if flow.active is not None: raise ValueError('Finish or cancel the current plan first.')
            flow.active='resetting_simulation'
        replacement=Tools('mock')
        try:
            await replacement.open()
            await self.tools.close()
            self.tools=replacement
            flow.tools=replacement
            return dict(ok=True,simulated=True)
        except BaseException:
            await replacement.close()
            raise
        finally:
            with flow.lock: flow.active=None

    def close(self):
        try: self.submit(self.tools.close()).result(timeout=5)
        finally: self.loop.call_soon_threadsafe(self.loop.stop)


def create_app(runtime,remote_login_password=None):
    app=Flask(__name__)
    app.config['MAX_CONTENT_LENGTH']=16384
    install_remote_access(app,remote_login_password)
    flow=runtime.workflow

    @app.before_request
    def local_mutations():
        if request.method=='POST' and request.headers.get('X-Lab-Control')!='local':
            return jsonify(error='Use the local dashboard to submit controls.'),403

    @app.get('/')
    def index(): return render_template('index.html', home_text=', '.join(f'{v:g}' for v in HOME))

    @app.get('/api/config')
    def config():
        return jsonify(printer_mode=runtime.tools.mode,demo=flow.demo,
            motion_enabled=runtime.tools.mode=='mock' or os.getenv('PRINTER_ALLOW_MOTION')=='1')

    @app.post('/api/prepare')
    def prepare():
        data=request.get_json()
        prompt=data.get('prompt','') if isinstance(data,dict) else ''
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>2000: raise ValueError('Provide a short request')
        rid=flow.new(prompt,chat_id=data.get('chat_id'),previous_run_ids=data.get('previous_run_ids'))
        runtime.submit(flow.prepare(rid))
        return jsonify(run_id=rid),202

    @app.get('/api/runs/<rid>')
    def status(rid): return jsonify(flow.get(rid))

    @app.get('/api/runs/<rid>/image')
    def target_image(rid):
        run=flow.get(rid)
        image=run.get('target',{}).get('annotated_image')
        if not image: raise ValueError('No captured target image')
        path=Path(image).resolve()
        allowed=ROOT.parent/'shape-scanner/results/images'
        if not path.is_relative_to(allowed.resolve()): raise ValueError('Invalid target image path')
        return send_file(path,conditional=False,max_age=0)

    def observation_file(rid,index=None):
        run=flow.get(rid);gallery=run.get('observation_images')
        if not gallery:raise ValueError('No captured observation images')
        observation=run.get('observation') or run.get('observation_view') or {}
        if gallery.get('frame_id')!=observation.get('frame_id'):
            raise ValueError('Observation image does not match the measured frame')
        if index is None:image=gallery['board_image']
        else:
            cells=gallery.get('cells',[])
            if not 0<=index<len(cells) or cells[index]['index']!=index:raise ValueError('Unknown observation cell image')
            if cells[index]['frame_id']!=gallery['frame_id']:raise ValueError('Cell image frame mismatch')
            image=cells[index]['image']
        path=Path(image).resolve()
        if not path.is_relative_to((ROOT/'results/observations').resolve()):raise ValueError('Invalid observation image path')
        if not path.is_file():raise ValueError('Observation image unavailable')
        return send_file(path,conditional=False,max_age=0)

    @app.get('/api/runs/<rid>/observation/board')
    def observation_board(rid):return observation_file(rid)

    @app.get('/api/runs/<rid>/observation/cells/<int:index>')
    def observation_cell(rid,index):return observation_file(rid,index)

    @app.post('/api/runs/<rid>/execute')
    def execute(rid):
        data=request.get_json()
        flow.approve(rid,data.get('confirmed'),data.get('clear_path'))
        runtime.submit(flow.execute(rid))
        return jsonify(ok=True),202

    @app.post('/api/runs/<rid>/cancel')
    def cancel(rid):
        flow.cancel(rid)
        return jsonify(ok=True)

    @app.post('/api/runs/<rid>/answer')
    def answer(rid):
        data=request.get_json()
        flow.claim_answer(rid,data.get('answer'))
        runtime.submit(flow.answer(rid))
        return jsonify(ok=True),202

    @app.post('/api/runs/<rid>/stop-task')
    def stop_task(rid):
        flow.request_stop(rid)
        return jsonify(ok=True)

    @app.get('/api/runs/<rid>/evidence/<int:index>/<side>')
    def evidence(rid,index,side):
        if side not in ('before','after'): raise ValueError('Invalid evidence side')
        records=flow.get(rid)['results']
        if not 0<=index<len(records): raise ValueError('Unknown target result')
        images=records[index].get('evidence',{}).get('images',[])
        if len(images)!=2: raise ValueError('No image evidence for this result')
        path=Path(images[0 if side=='before' else 1]).resolve()
        if not path.is_relative_to((ROOT/'results/evidence').resolve()): raise ValueError('Invalid evidence path')
        return send_file(path,conditional=False,max_age=0)

    @app.post('/api/simulation/reset')
    def reset_simulation():
        return jsonify(runtime.submit(runtime.reset_mock()).result(timeout=30))

    @app.post('/api/stop')
    def stop():
        if request.get_json().get('confirmed') is not True: raise ValueError('Confirm emergency shutdown')
        with flow.lock:
            if flow.active in flow.runs: flow.runs[flow.active]['stop_requested']=True
        result=runtime.submit(runtime.tools.call('printer','emergency_stop')).result(timeout=15)
        return jsonify(result)

    @app.errorhandler(ValueError)
    def invalid(exc): return jsonify(error=str(exc)),409

    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo',action='store_true',help='Camera-free scripted target and mock LLM; always simulated printer')
    parser.add_argument('--printer-mode',choices=['mock','real'],default='mock')
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--port',type=int,default=8770)
    parser.add_argument('--host',default='127.0.0.1',help='Use 0.0.0.0 to allow password-protected access from the same Wi-Fi')
    args=parser.parse_args()
    load_dotenv(args.env_file,override=False)
    if args.demo and args.printer_mode!='mock': parser.error('Demo cannot target real hardware')
    if not args.demo and not os.getenv('GROQ_API_KEY'): parser.error('Set GROQ_API_KEY locally or use --env-file; --demo needs no key')
    login_password=None
    if not is_loopback(args.host):
        try:login_password,password_file=remote_password(ROOT)
        except ValueError as exc:parser.error(str(exc))
        print('Remote browser login: username lab',flush=True)
        print(f'Password file: {password_file}' if password_file else 'Password: LAB_REMOTE_PASSWORD from your environment',flush=True)
    runtime=Runtime(args.printer_mode,args.demo)
    atexit.register(runtime.close)
    print(f'Open http://127.0.0.1:{args.port} · printer={args.printer_mode} · synthetic={args.demo}',flush=True)
    create_app(runtime,login_password).run(host=args.host,port=args.port,threaded=True,debug=False)
