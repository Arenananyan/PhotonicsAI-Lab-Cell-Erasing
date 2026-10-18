"""Operator-defined circular wiping path. All legs are validated by the printer backend."""
import math
HOME = [209.0, 208.0, 100.0]
SPEED = 20.0
CONTACT_Z = 14.5
CIRCLE_RADIUS = 10.0
CIRCLE_SEGMENTS = 72


def make_plan(start: list[float], target: dict) -> dict:
    values = list(start) + [target['x'], target['y']]
    if len(start)!=3 or any(isinstance(v, bool) or not isinstance(v, (int,float))
                           or not math.isfinite(v) for v in values):
        raise ValueError('Invalid numeric coordinates')
    current = [round(float(v),3) for v in start]
    xy = [round(float(target[a]),3) for a in ('x','y')]
    # Approach and departure stay at clearance height. The closed polygon starts
    # at +Y; decreasing mathematical angles give clockwise rotation in printer XY.
    circle = [[round(xy[0] + CIRCLE_RADIUS*math.sin(2*math.pi*k/CIRCLE_SEGMENTS),3),
               round(xy[1] + CIRCLE_RADIUS*math.cos(2*math.pi*k/CIRCLE_SEGMENTS),3),
               CONTACT_Z] for k in range(CIRCLE_SEGMENTS+1)]
    waypoints = [[current[0],current[1],HOME[2]], [xy[0],current[1],HOME[2]],
                 [xy[0],xy[1],HOME[2]], [xy[0],xy[1],CONTACT_Z]] + circle + [
                 [circle[-1][0],circle[-1][1],HOME[2]],
                 [HOME[0],circle[-1][1],HOME[2]], HOME[:]]
    steps = []
    path = []
    for end in waypoints:
        delta = [round(end[i]-current[i],3) for i in range(3)]
        if delta[0] and delta[1]:
            if delta[2]: raise ValueError('XY travel must not change Z')
            steps.append({'axis':'xy','distance_mm':delta[:2]})
        else:
            for i,axis in enumerate('xyz'):
                if delta[i]: steps.append({'axis':axis,'distance_mm':delta[i]})
        if end != current:
            path.append(end[:])
        current=end[:]
    return dict(start=[round(float(v),3) for v in start], target=xy,
                home=HOME[:], low_z_mm=CONTACT_Z, speed_mm_s=SPEED,
                waypoints=path, steps=steps,
                circle=dict(center_mm=xy, radius_mm=CIRCLE_RADIUS, direction="clockwise",
                            revolutions=1, segments=CIRCLE_SEGMENTS),
                note='Home is a named position, not firmware homing. One clockwise polygonal wiping pass; physical erasure is not verified. No heating or extrusion.')


def make_home_plan(start: list[float]) -> dict:
    """Lift to clearance first, then X, then Y. No firmware homing."""
    if len(start)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in start):
        raise ValueError('Invalid starting coordinates')
    current=[round(float(v),3) for v in start]
    path=[];steps=[]
    for i in (2,0,1):
        delta=round(HOME[i]-current[i],3)
        if delta:
            current[i]=HOME[i]
            path.append(current[:]);steps.append(dict(axis='xyz'[i],distance_mm=delta))
    return dict(kind='home',start=[round(float(v),3) for v in start],home=HOME[:],
                waypoints=path,steps=steps,speed_mm_s=SPEED,
                note='Move to the named observation position: Z first, then X, then Y. Recognition follows arrival. No G28.')


def make_move_plan(start: list[float], coordinates: dict, coordinate_system='printer') -> dict:
    """Explicit XYZ destination: raise, translate, descend, remain at destination."""
    if len(start)!=3 or set(coordinates)!=set('xyz'):
        raise ValueError('Three starting and destination coordinates are required')
    values=list(start)+[coordinates[a] for a in 'xyz']
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
        raise ValueError('Invalid numeric coordinates')
    if coordinate_system not in ('printer','paper'): raise ValueError('Unknown coordinate system')
    destination=[float(coordinates[a]) for a in 'xyz']
    if coordinate_system=='paper':
        destination[0]+=9; destination[1]+=8
    destination=[round(v,3) for v in destination]
    current=[round(float(v),3) for v in start]
    height=max(HOME[2],current[2],destination[2])
    path=[];steps=[]
    for axis,value in ((2,height),(0,destination[0]),(1,destination[1]),(2,destination[2])):
        delta=round(value-current[axis],3)
        if delta:
            current[axis]=value
            path.append(current[:]);steps.append(dict(axis='xyz'[axis],distance_mm=delta))
    return dict(kind='move',start=list(start),destination=destination,waypoints=path,steps=steps,
                speed_mm_s=SPEED,clearance_z_mm=height)
