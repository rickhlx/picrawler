"""Body-frame geometry.

Gait frames in picrawler.py are written in each leg's local frame: x points
sideways out of the body, y points along the body away from its centre, z is
height (negative is down). Balance and gait generation are simpler in one
shared body frame (REP-103: x forward, y left, z up, origin at the centre of
the hip square), so this module converts between the two.
"""
import math

HALF_SIDE = 77 / 2  # hips sit on the corners of a 77 mm square

# Per leg, in Picrawler order (right front, left front, left rear, right rear):
# sign of body x for "along the body, outward" and of body y for "sideways, outward".
_LEG_SIGNS = ((1, -1), (1, 1), (-1, 1), (-1, -1))


def to_body(leg, coord):
    """Leg-local [x, y, z] -> body-frame [x, y, z]."""
    sx, sy = _LEG_SIGNS[leg]
    x, y, z = coord
    return [sx * (HALF_SIDE + y), sy * (HALF_SIDE + x), z]


def to_leg(leg, point):
    """Body-frame [x, y, z] -> leg-local [x, y, z]."""
    sx, sy = _LEG_SIGNS[leg]
    bx, by, bz = point
    return [sy * by - HALF_SIDE, sx * bx - HALF_SIDE, bz]


def rotate(points, roll=0.0, pitch=0.0):
    """Foot positions in the body frame after the body rolls and pitches about
    its centre (degrees, REP-103: roll + lifts the left side, pitch + drops the
    nose) while the feet stay where they are on the ground."""
    cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    rotated = []
    for x, y, z in points:
        # R = Ry(pitch) Rx(roll); feet fixed in the world means p' = R^T p.
        x, z = cp * x - sp * z, sp * x + cp * z
        y, z = cr * y + sr * z, -sr * y + cr * z
        rotated.append([x, y, z])
    return rotated


def to_step(points, roll=0.0, pitch=0.0):
    """Body-frame foot positions -> a frame for Picrawler.do_step, optionally
    with the body rotated."""
    return [to_leg(i, p) for i, p in enumerate(rotate(points, roll, pitch))]
