"""Validate LLM proposals against measured data and the operator's task scope."""
import math
from .observation import point

class AmbiguousSize(ValueError):
    def __init__(self, options):
        self.options=options
        super().__init__('Cell sizes are too close to select uniquely; clarify the target (within 5%).')


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_task(task):
    from .spatial import validate_selector
    if not isinstance(task, dict) or task.get('action') not in ('wipe', 'move', 'home', 'inspect', 'ask', 'reject'):
        raise ValueError('Invalid LLM task')
    if not isinstance(task.get('message'), str) or not task['message'].strip():
        raise ValueError('LLM must explain its task or question')
    speed=task.get('speed_mm_s')
    if speed is not None and (not finite(speed) or not 0 < speed <= 30):
        raise ValueError('Speed must be greater than 0 and at most 30 mm/s')
    condition=task.get('condition')
    if condition is not None:
        metrics={'blue_count','green_count','total_count','blue_area_mm2','green_area_mm2'}
        if (task['action'] not in ('wipe','move','home') or not isinstance(condition,dict)
                or set(condition)!={'metric','operator','value','compare_metric'}
                or condition['metric'] not in metrics
                or condition['operator'] not in ('gt','gte','eq','lt','lte')
                or (condition['compare_metric'] is None)==(condition['value'] is None)
                or (condition['compare_metric'] is not None and condition['compare_metric'] not in metrics)
                or (condition['value'] is not None and not finite(condition['value']))):
            raise ValueError('Unsupported or incomplete measured condition')
    if task['action'] == 'wipe':
        if task.get('color') not in ('blue', 'green') or task.get('selection') not in ('largest', 'smallest', 'all', 'nearest'):
            raise ValueError('Invalid color or selection scope')
    if task.get('selection') == 'nearest':
        if task['action'] not in ('wipe','inspect','move'): raise ValueError('Nearest selection requires a cell operation')
        validate_selector(task.get('reference'))
    elif task.get('reference') is not None:
        raise ValueError('Reference requires nearest selection')
    if task.get('distance_between') is not None:
        pair=task['distance_between']
        if task['action']!='inspect' or not isinstance(pair,list) or len(pair)!=2:
            raise ValueError('Distance requires exactly two read-only selectors')
        for selector in pair: validate_selector(selector)
    if task.get('observe_from_home') is not None:
        if not isinstance(task['observe_from_home'],bool) or (task['observe_from_home'] and task['action']!='inspect'):
            raise ValueError('Home observation is only supported for inspection')
    if task.get('use_previous_target') is not None:
        if not isinstance(task['use_previous_target'],bool) or (task['use_previous_target'] and task['action'] not in ('move','inspect')):
            raise ValueError('Previous-target references require an inspect or move task')
    if task['action'] == 'home' and any(task.get(k) is not None for k in ('color','selection','coordinates','coordinate_system')):
        raise ValueError('Named home cannot override coordinates or include a wiping scope')
    if task['action'] == 'move':
        xyz=task.get('coordinates')
        if task.get('use_previous_target') or (xyz is None and task.get('selection')):
            if xyz is not None:raise ValueError('Cell moves must use measured coordinates, not model-generated XYZ')
            if task.get('use_previous_target') is not True and (task.get('color') not in ('blue','green') or task.get('selection') not in ('largest','smallest','nearest')):
                raise ValueError('Invalid cell movement selector')
            return task
        if not isinstance(xyz, dict) or set(xyz) != set('xyz') or not all(finite(xyz[k]) for k in 'xyz'):
            raise ValueError('All three finite XYZ coordinates are required')
        # The operator-defined default is absolute printer mm, even if the
        # model leaves the nullable schema field empty. Preserve explicit paper.
        if task.get('coordinate_system') is None:
            task=dict(task,coordinate_system='printer')
        if task.get('coordinate_system') not in ('printer', 'paper'):
            raise ValueError('Unknown coordinate system')
    return task


def selected_cells(cells, task):
    """Measurement validator, never interprets language or supplies an LLM choice."""
    if task.get('selection')=='nearest':
        from .spatial import nearest
        return [nearest(cells,task)[1]]
    eligible=[c for c in cells if c['color']==task['color']]
    if not eligible:
        raise ValueError('No cells of the requested color are visible')
    if task['selection']=='all':
        return eligible
    ordered=sorted(eligible,key=lambda c:c['area_mm2'],reverse=task['selection']=='largest')
    if len(ordered)>1 and abs(ordered[0]['area_mm2']-ordered[1]['area_mm2']) <= .05*max(ordered[0]['area_mm2'],ordered[1]['area_mm2']):
        raise AmbiguousSize([c for c in ordered if abs(c['area_mm2']-ordered[0]['area_mm2'])<=.05*max(c['area_mm2'],ordered[0]['area_mm2'])])
    return ordered[:1]


def validate_selection(reply, cells, task):
    ids=reply.get('target_ids')
    if not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):
        raise ValueError('LLM returned missing or duplicate target IDs')
    by_id={c['target_id']:c for c in cells}
    expected={c['target_id'] for c in selected_cells(cells,task)}
    if set(ids)!=expected:
        raise ValueError('LLM selection is outside the approved scope or measured ranking')
    return [by_id[i] for i in ids]


def associate(target, cells, tolerance=3.0):
    matches=[c for c in cells if c['color']==target['color'] and math.dist(point(c),point(target))<=tolerance]
    if len(matches)!=1:
        raise ValueError('Target missing, split, or ambiguous; no movement sent')
    return matches[0]


def evaluate_condition(condition,cells):
    """Evaluate one LLM-interpreted comparison against current measured cells."""
    values={color+'_count':sum(c['color']==color for c in cells) for color in ('blue','green')}
    values['total_count']=values['blue_count']+values['green_count']
    for color in ('blue','green'):
        values[color+'_area_mm2']=sum(c['area_mm2'] for c in cells if c['color']==color)
    left=values[condition['metric']]
    right=condition['value'] if condition['compare_metric'] is None else values[condition['compare_metric']]
    op=condition['operator']
    passed={'gt':left>right,'gte':left>=right,'eq':left==right,'lt':left<right,'lte':left<=right}[op]
    return dict(passed=passed,left=left,right=right,values=values,condition=condition)
