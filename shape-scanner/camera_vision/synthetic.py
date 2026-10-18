"""Deterministic hardware-free scenes used by demos and tests."""
import cv2
import numpy as np
from .errors import VisionError

SCENES = ('one_red', 'multiple_red', 'no_red', 'mixed', 'noise', 'dim')


def make_scene(name: str = 'mixed', defective_color: str = 'red') -> np.ndarray:
    if name not in SCENES:
        raise VisionError('INVALID_SCENE', f'Choose one of: {", ".join(SCENES)}')
    image = np.full((480, 640, 3), 235, np.uint8)
    for x in range(0, 640, 25):
        cv2.line(image, (x, 0), (x, 479), (210, 202, 198), 1)
    for y in range(0, 480, 25):
        cv2.line(image, (0, y), (639, y), (210, 202, 198), 1)
    if name == 'one_red':
        red, green = [(180, 160, 42)], []
    elif name == 'multiple_red':
        red, green = [(130, 140, 35), (350, 150, 45), (260, 340, 30)], []
    elif name == 'no_red':
        red, green = [], [(180, 180, 40)]
    else:
        red = [(160, 140, 40), (380, 330, 32)]
        green = [(400, 140, 44), (170, 335, 30)]
    defect_ink = (30, 30, 205) if defective_color == 'red' else (205, 80, 30)
    for color, circles in [(defect_ink, red), ((45, 170, 45), green)]:
        for x, y, radius in circles:
            cv2.circle(image, (x, y), radius, color, -1)
    if name == 'noise':
        rng = np.random.default_rng(12)
        image = np.clip(image.astype(float)+rng.normal(0, 12, image.shape), 0, 255).astype(np.uint8)
        for x, y in rng.integers([0, 0], [640, 480], size=(90, 2)):
            cv2.circle(image, (int(x), int(y)), 1, (0, 0, 220), -1)
    if name == 'dim':
        image = (image.astype(float)*.38).astype(np.uint8)
    return image
