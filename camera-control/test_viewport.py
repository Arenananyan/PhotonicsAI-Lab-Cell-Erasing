import io
import unittest
from PIL import Image
from app import create_app
from viewport import Viewport


def jpeg():
    im=Image.new('RGB',(400,200),(200,10,10))
    im.paste((10,10,200),(200,0,400,200))
    out=io.BytesIO();im.save(out,'JPEG');return out.getvalue()


class ViewTests(unittest.TestCase):
    def test_zoom_and_pan_crop_mapping(self):
        v=Viewport();v.control('zoom',2)
        _,m=v.render(jpeg());self.assertEqual(m['crop_pixels'],{'x':100,'y':50,'width':200,'height':100})
        v.control('pan',direction='right',step=.5)
        image,m=v.render(jpeg());self.assertEqual(m['crop_pixels']['x'],200)
        self.assertEqual(Image.open(io.BytesIO(image)).size,(400,200))
        self.assertGreater(Image.open(io.BytesIO(image)).getpixel((200,100))[2],150)

    def test_limits_reset_and_one_x_pan(self):
        v=Viewport();self.assertEqual(v.control('pan',direction='right')['center_x'],.5)
        v.control('zoom',8)
        for _ in range(20):v.control('pan',direction='up',step=1)
        self.assertEqual(v.state()['center_y'],1/16)
        self.assertEqual(v.control('reset')['zoom'],1)
        self.assertEqual(v.state()['center_y'],.5)

    def test_invalid_controls(self):
        for args in [('zoom',0),('zoom',float('nan')),('zoom',9),('nonsense',None)]:
            with self.assertRaises(ValueError):Viewport().control(*args)
        with self.assertRaises(ValueError):Viewport().control('pan',direction='bad')
        with self.assertRaises(ValueError):Viewport().control('pan',direction='left',step=-1)

    def test_full_frame_endpoint_is_unchanged(self):
        payload=jpeg()
        class Receiver:
            def snapshot(self):return payload
        client=create_app(None,Receiver()).test_client()
        before=client.get('/snapshot.jpg').data
        r=client.post('/api/view',json={'action':'zoom','value':3},headers={'X-Camera-Control':'local'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(client.get('/snapshot.jpg').data,before)
        view=client.get('/snapshot-view.jpg')
        self.assertEqual(view.status_code,200)
        self.assertIn('crop_pixels',view.headers['X-View-Metadata'])
        self.assertNotEqual(view.data,before)
        self.assertEqual(client.post('/api/view',json={'action':'reset'}).status_code,403)


if __name__=='__main__':unittest.main()
