"""Crowd-pleaser tricks as body-frame keyframes.

Each trick is a function returning a list of ``Move``: body-frame foot
positions (see body.py), the servo speed to reach them, and how long to hold
the pose. Every trick starts and ends in ``gait.NEUTRAL``, so it runs inside
``Picrawler.neutral_stance``; ``Picrawler.trick`` does both.
"""
import math
from typing import NamedTuple

from . import body, gait

NEUTRAL = gait.NEUTRAL
# pause at each reversal of a wiggle so the servos' current spike settles first
SETTLE = 0.08


class Move(NamedTuple):
    feet: list          # body-frame foot positions, one per leg
    speed: int = 60     # do_step speed, 0-100
    hold: float = 0.0   # seconds to stay in the pose once reached


def pose(x=0.0, y=0.0, z=0.0, roll=0.0, pitch=0.0, yaw=0.0, feet=NEUTRAL):
    """Foot positions when the body shifts by (x, y, z) mm and turns by
    roll/pitch/yaw degrees while the feet stay planted (REP-103 signs; yaw +
    turns the nose left)."""
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    shifted = []
    for fx, fy, fz in feet:
        fx, fy, fz = fx - x, fy - y, fz - z
        shifted.append([cy * fx + sy * fy, -sy * fx + cy * fy, fz])
    return body.rotate(shifted, roll, pitch)


def _local(frame):
    """Leg-local do_step frame -> body-frame feet."""
    return [body.to_body(i, c) for i, c in enumerate(frame)]


def bow():
    """Sink back and dip the nose, hold, rise."""
    return [
        Move(pose(x=-10, z=-5, pitch=12), speed=45, hold=0.8),
        Move(pose(), speed=50),
    ]


def nod():
    """Yes."""
    moves = []
    for _ in range(2):
        moves += [Move(pose(pitch=10), speed=55), Move(pose(pitch=-6), speed=55)]
    return moves + [Move(pose(), speed=60)]


def shake_head():
    """No."""
    moves = []
    for _ in range(3):
        moves += [Move(pose(yaw=10), speed=55, hold=SETTLE), Move(pose(yaw=-10), speed=55, hold=SETTLE)]
    return moves + [Move(pose(), speed=60)]


def shimmy():
    """Get low and wiggle: yaw with a counter-roll, like shoulders going.
    Kept small and slow: every servo reverses on each wiggle, and fast
    reversals browned the Pi 5 out (docs/pi-config.md, Power)."""
    moves = []
    for _ in range(3):
        moves += [Move(pose(z=-4, yaw=7, roll=-4), speed=50, hold=SETTLE),
                  Move(pose(z=-4, yaw=-7, roll=4), speed=50, hold=SETTLE)]
    return moves + [Move(pose(), speed=60)]


def hula(radius=18, tilt=6, points=12):
    """Body circles, one each way, leaning into the circle."""
    def circle(direction):
        frames = []
        for k in range(points + 1):
            a = direction * 2 * math.pi * k / points
            c, s = math.cos(a), math.sin(a)
            # lean toward the side the body has moved to
            frames.append(Move(pose(x=radius * c, y=radius * s, roll=-tilt * s, pitch=tilt * c), speed=55))
        return frames
    return circle(1) + circle(-1) + [Move(pose(), speed=60)]


def bounce(height=18, times=3):
    """Excited up-and-down bounce."""
    moves = []
    for _ in range(times):
        moves += [Move(pose(z=height), speed=80), Move(pose(z=-height), speed=80)]
    return moves + [Move(pose(), speed=70)]


def spin(turn=15, half_cycles=24):
    """Trot on the spot, turning left turn degrees per half cycle (negative
    spins right). 15 deg is the turn cap 23_trot.py uses; feet slip, so
    24 x 15 deg lands short of a full turn."""
    trot = gait.Trot()
    frames = []
    for _ in range(half_cycles):
        frames += trot.half_cycle(turn=turn)
    frames += trot.settle()
    return [Move(f, speed=85) for f in frames]


def play_dead():
    """Drop to the belly, legs in the air, twitch, lie still, get back up.
    Leg poses from examples/14_preset_actions.py; the flat and legs-up poses
    are past the shoulder limit, so set_angle clamps them to its end stop."""
    flat = _local([[45, 45, -10]] * 4)
    legs_up = _local([[45, 45, 100]] * 4)
    twitch_a = _local([[45, 35, 60], [35, 45, 80], [35, 45, 80], [45, 35, 60]])
    twitch_b = _local([[35, 45, 80], [45, 35, 60], [45, 35, 60], [35, 45, 80]])
    return (
        [Move(flat, speed=60), Move(legs_up, speed=70)]
        + [Move(twitch_a if k % 2 == 0 else twitch_b, speed=65) for k in range(6)]
        + [Move(legs_up, speed=55, hold=1.5), Move(flat, speed=55), Move(NEUTRAL, speed=50)]
    )


def high_five():
    """Plant three feet in a wide tripod, raise the left front leg, hold it
    up for the slap, put it down. Weights from the shake_hand pose in
    examples/14_preset_actions.py."""
    # Pull the left rear foot forward so the body sits inside the tripod.
    tripod = [list(p) for p in NEUTRAL]
    tripod[2] = body.to_body(2, [45, 0, -50])
    braced = [[45, 45, -65], [45, 45, -30], [45, 0, -60], [45, 45, -40]]
    raised = [[45, 45, -65], [10, 120, 75], [45, 0, -60], [45, 45, -40]]
    return (
        [Move(f, speed=70) for f in gait.reposition(NEUTRAL, tripod)]
        + [Move(_local(braced), speed=55), Move(_local(raised), speed=70, hold=1.2),
           Move(_local(braced), speed=60), Move(tripod, speed=55)]
        + [Move(f, speed=70) for f in gait.reposition(tripod, NEUTRAL)]
    )


TRICKS = {
    "bow": bow,
    "nod": nod,
    "shake head": shake_head,
    "shimmy": shimmy,
    "hula": hula,
    "bounce": bounce,
    "spin": spin,
    "play dead": play_dead,
    "high five": high_five,
}
