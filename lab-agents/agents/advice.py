"""Measured read-only cell report and bounded action suggestions."""
import math


def ranked_cells(observation):
    if not observation.get('available') or (observation.get('calibration') or {}).get('status') != 'valid':
        return []
    cells=[]
    for cell in observation.get('cells', []):
        xy=cell.get('printer_coordinates_mm')
        area=cell.get('area_mm2')
        if (cell.get('color') not in ('blue','green') or not isinstance(xy,dict)
                or isinstance(area,bool) or not isinstance(area,(int,float)) or not math.isfinite(area) or area<=0
                or any(isinstance(xy.get(axis),bool) or not isinstance(xy.get(axis),(int,float))
                       or not math.isfinite(xy[axis]) for axis in ('x','y'))):
            continue
        cells.append(dict(detection_id=cell.get('detection_id'),color=cell['color'],area_mm2=area,
                          printer_coordinates_mm=dict(x=xy['x'],y=xy['y'])))
    return sorted(cells,key=lambda c:(('blue','green').index(c['color']),-c['area_mm2'],
                                      c['printer_coordinates_mm']['x'],c['printer_coordinates_mm']['y']))


def suggestion_catalog(facts,ranked,english=False):
    """Offer only commands the current bounded task contract can represent."""
    if english:
        catalog=[dict(id='status',prompt='Where is the printer head and is the camera ready?',label='Check printer and camera status')]
    else:
        catalog=[dict(id='status',prompt='Որտե՞ղ է գլխիկը, և կամերան պատրա՞ստ է։',label='Ստուգել պրինտերն ու կամերան')]
    if not ranked:
        catalog.append(dict(id='home_view',prompt='Go home then inspect the board' if english else 'Գնա տուն, հետո նորից դիտիր տախտակը։',
                            label='Inspect from home (approval required)' if english else 'Դիտել տանից՝ ճանապարհը հաստատելուց հետո'))
        catalog.append(dict(id='retry_view',prompt='Check the camera and board calibration again' if english else 'Նորից ստուգիր կամերան ու տախտակի կալիբրացիան։',
                            label='Recheck the view' if english else 'Նորից ստուգել պատկերը'))
        return catalog
    catalog.append(dict(id='ranked',prompt='Show visible blue and green cells separately, largest to smallest, with coordinates' if english else 'Ցույց տուր կապույտ և կանաչ բջիջները առանձին՝ մեծից փոքր, կոորդինատներով։',
                        label='Show cells by size' if english else 'Ցույց տալ բջիջները մեծից փոքր'))
    for color in ('blue','green'):
        group=[cell for cell in ranked if cell['color']==color]
        if not group: continue
        hy='կապույտ' if color=='blue' else 'կանաչ'
        if len(group)==1 or group[0]['area_mm2']>group[1]['area_mm2']*1.05:
            catalog.append(dict(id='largest_'+color,
                prompt=f'Clean the largest {color} cell' if english else f'Մաքրիր ամենամեծ {hy} բջիջը։',
                label=f'Clean largest {color}' if english else f'Մաքրել ամենամեծ {hy}ը'))
        if 1<len(group)<=20:
            catalog.append(dict(id='all_'+color,
                prompt=f'Clean all {color} cells' if english else f'Մաքրիր բոլոր {hy} բջիջները։',
                label=f'Clean all {color}' if english else f'Մաքրել բոլոր {hy}ները'))
    return catalog


def validate_recommendations(reply,catalog):
    ids=reply['suggestion_ids']
    if len(ids)>3 or len(ids)!=len(set(ids)):
        raise ValueError('At most three distinct suggestions are allowed')
    by_id={item['id']:item for item in catalog}
    if any(item not in by_id for item in ids):
        raise ValueError('LLM suggested an operation outside the measured catalog')
    return [by_id[item] for item in ids]
