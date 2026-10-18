"""Run while app.py is receiving video. Saves one frame; does not change settings."""
from pathlib import Path
from urllib.request import urlopen
from blackmagic_camera import BlackmagicCamera

camera = BlackmagicCamera('127.0.0.1')
print(camera.status())

# Uncomment the controls you want to use:
# camera.set_zoom(0.03)        # Normalized 0..1, NOT 3% optical magnification.
# camera.set_focus(0.7)       # Normalized lens position, not metres.
# camera.autofocus()
# camera.set_iso(400)
# camera.set_white_balance(5500)

with urlopen('http://127.0.0.1:8765/snapshot.jpg', timeout=5) as response:
    image_bytes = response.read()
path = Path(__file__).parent / 'captures' / 'example.jpg'
path.parent.mkdir(exist_ok=True)
path.write_bytes(image_bytes)
print('Saved', path)
