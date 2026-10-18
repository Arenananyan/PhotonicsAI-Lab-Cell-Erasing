"""Edit STEPS, then run ./printerctl. Distances are in mm."""
from simple_runner import fw, bc, x, y, z, run

SPEED = 20.0
Z_SPEED = 20.0
# Z examples to add to STEPS: fw(z, 5) raises 5 mm; bc(z, 5) lowers 5 mm.
# Every target is checked against the printer's reported firmware travel limits.
STEPS = [
    fw(y, 50),
]

if __name__ == '__main__':
    raise SystemExit(run(STEPS, SPEED, z_speed=Z_SPEED))
