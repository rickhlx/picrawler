"""Small idle gestures, made while the robot talks.

Unlike tricks, a fidget starts from wherever the feet are (usually the sit
pose) and returns there, so it needs no stand or neutral stance. Moves are a
few degrees or millimetres at a slow speed: all twelve servos may move, but
barely, so the current draw stays far below a trick's while the amp is busy.
"""
import random

from . import body
from .tricks import Move, pose

SPEED = 30


def _there_and_back(feet, target, hold):
    return [Move(target, speed=SPEED, hold=hold), Move(feet, speed=SPEED)]


def tilt(feet):
    """Cock the head to one side."""
    return _there_and_back(feet, pose(roll=random.choice((-5, 5)), feet=feet), 0.8)


def glance(feet):
    """Turn the body a little to one side, as if looking."""
    return _there_and_back(feet, pose(yaw=random.choice((-7, 7)), feet=feet), 0.7)


def nod(feet):
    """A single small dip of the nose."""
    return _there_and_back(feet, pose(pitch=5, feet=feet), 0.2)


def lean(feet):
    """Shift the weight forward or back."""
    return _there_and_back(feet, pose(x=random.choice((-6, 6)), feet=feet), 1.0)


def tap(feet):
    """Lift a front foot a little and put it down."""
    leg = random.choice((0, 1))
    lifted = [list(p) for p in feet]
    lifted[leg][2] += 10
    return _there_and_back(feet, lifted, 0.3)


FIDGETS = {"tilt": tilt, "glance": glance, "nod": nod, "lean": lean, "tap": tap}


def fidget(name, frame):
    """Moves for the named fidget from the leg-local do_step frame the robot
    is in."""
    return FIDGETS[name]([body.to_body(i, c) for i, c in enumerate(frame)])
