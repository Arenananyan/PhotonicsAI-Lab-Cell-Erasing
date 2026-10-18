"""Digital viewing crop. Does not alter the phone or full-frame scanner feed."""
import io
import math
import threading
from PIL import Image


class Viewport:
    def __init__(self):
        self.lock = threading.RLock()
        self.zoom = 1.0
        self.x = self.y = .5

    def state(self):
        with self.lock:
            half = .5 / self.zoom
            return {'zoom': self.zoom, 'center_x': self.x, 'center_y': self.y,
                    'crop_normalized': {'x': self.x-half, 'y': self.y-half,
                                        'width': 1/self.zoom, 'height': 1/self.zoom},
                    'coordinate_space': 'full_frame_normalized', 'digital': True}

    def control(self, action, value=None, direction=None, step=.2):
        with self.lock:
            if action == 'zoom':
                try:
                    value = float(value)
                except (TypeError,ValueError) as exc:
                    raise ValueError('Digital zoom must be a number from 1 to 8.') from exc
                if not math.isfinite(value) or not 1 <= value <= 8:
                    raise ValueError('Digital zoom must be 1..8.')
                self.zoom = value
            elif action == 'pan':
                try:
                    step = float(step)
                except (TypeError,ValueError) as exc:
                    raise ValueError('Pan step must be a number.') from exc
                if not math.isfinite(step) or not 0 < step <= 1:
                    raise ValueError('Pan step must be >0 and <=1 of the visible crop.')
                if direction not in ('left','right','up','down'):
                    raise ValueError('Direction must be left, right, up or down.')
                delta = step/self.zoom
                self.x += delta * ((direction=='right')-(direction=='left'))
                self.y += delta * ((direction=='down')-(direction=='up'))
            elif action == 'reset':
                self.zoom, self.x, self.y = 1.0, .5, .5
            else:
                raise ValueError('Use zoom, pan or reset.')
            half=.5/self.zoom
            self.x=min(1-half,max(half,self.x));self.y=min(1-half,max(half,self.y))
            return self.state()

    def render(self, payload):
        with self.lock:
            state=self.state()
        image=Image.open(io.BytesIO(payload)).convert('RGB')
        width,height=image.size;c=state['crop_normalized']
        left=round(c['x']*width);top=round(c['y']*height)
        right=min(width,round((c['x']+c['width'])*width))
        bottom=min(height,round((c['y']+c['height'])*height))
        crop=image.crop((left,top,right,bottom)).resize((width,height),Image.Resampling.LANCZOS)
        out=io.BytesIO();crop.save(out,'JPEG',quality=88)
        state.update(source_width=width,source_height=height,output_width=width,output_height=height,
            crop_pixels={'x':left,'y':top,'width':right-left,'height':bottom-top},
            mapping='source_x=crop.x+view_x*crop.width/output_width; same for y')
        return out.getvalue(),state
