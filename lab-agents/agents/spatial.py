"""Measured planar geometry; language interpretation stays with the LLM."""
import math
from .observation import point


class AmbiguousNearest(ValueError):
    def __init__(self, reference, options):
        self.reference, self.options = reference, options
        super().__init__('Nearest cells are within 3 mm of each other in distance to the reference; clarify the target. '
                         + str([dict(option=i+1,xy=point(c),distance_mm=round(distance(reference,c),3)) for i,c in enumerate(options)]))


def validate_selector(value):
    if (not isinstance(value, dict) or set(value) != {'color', 'selection'}
            or value['color'] not in ('blue', 'green')
            or value['selection'] not in ('largest', 'smallest')):
        raise ValueError('A spatial reference needs a color and largest/smallest selection')


def distance(a, b):
    return math.dist(point(a), point(b))


def nearest(cells, task):
    from .contracts import selected_cells
    reference = selected_cells(cells, task['reference'])[0]
    eligible = [c for c in cells if c['color'] == task['color'] and c is not reference]
    if not eligible:
        raise ValueError('No other cell of the requested color is visible')
    ordered = sorted(eligible, key=lambda c: distance(reference, c))
    if len(ordered) > 1 and distance(reference, ordered[1]) - distance(reference, ordered[0]) <= 3.0:
        raise AmbiguousNearest(reference,[c for c in ordered if distance(reference,c)-distance(reference,ordered[0])<=3.0])
    return reference, ordered[0]


def measurement(a, b, frame_id):
    return dict(from_target_id=a['target_id'], to_target_id=b['target_id'],
                from_detection_id=a.get('detection_id'), to_detection_id=b.get('detection_id'),
                from_xy_mm=point(a), to_xy_mm=point(b), distance_mm=distance(a, b),
                definition='center-to-center XY', units='mm', frame_id=frame_id)


def spatial_evidence(cells, task, frame_id):
    """Expose calculated distances to the selection model, never invented numbers."""
    from .contracts import selected_cells
    if task.get('selection')!='nearest' and not task.get('distance_between'):return []
    ids=[c['target_id'] for c in cells]
    if len(ids)!=len(set(ids)) or any(c.get('frame_id',frame_id)!=frame_id for c in cells):
        raise ValueError('Spatial measurement IDs or frames disagree')
    if task.get('selection') == 'nearest':
        reference, target = nearest(cells, task)
        return [measurement(reference, c, frame_id) for c in cells
                if c['color'] == task['color'] and c is not reference]
    pair = task.get('distance_between')
    if pair:
        a, b = [selected_cells(cells, selector)[0] for selector in pair]
        if a['target_id'] == b['target_id']:
            raise ValueError('Both selectors identify the same cell; specify two different cells')
        return [measurement(a, b, frame_id)]
    return []
