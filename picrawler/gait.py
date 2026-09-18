"""Trot gait: diagonal leg pairs swing together.

The MoveList gaits are crawls, lifting one leg at a time over seven frames.
A trot lifts two at once, so each half cycle moves the body a full stride and
needs only a few frames. Frames are body-frame foot positions; turn them into
``do_step`` frames with ``body.to_step``.
"""
import math

from . import body

# Symmetric stance: every foot at leg-local (45, 45, -50).
NEUTRAL = [body.to_body(i, [45, 45, -50]) for i in range(4)]

_PAIRS = ((0, 2), (1, 3))  # right front + left rear, left front + right rear


def _lerp(a, b, u):
    return [x + (y - x) * u for x, y in zip(a, b)]


class Trot:
    """Stateful trot generator.

    Each ``half_cycle`` swings one diagonal pair toward where it should land
    for the requested motion while the other pair sweeps back on the ground,
    then swaps pairs for the next call. Because it starts from wherever the
    feet are, speed and direction can change every half cycle, and a couple of
    zero-motion half cycles bring the feet back to ``neutral``.
    """

    def __init__(self, feet=None, neutral=NEUTRAL, lift=15, frames=4):
        self.neutral = [list(p) for p in neutral]
        self.feet = [list(p) for p in (feet or neutral)]
        self.lift = lift
        self.frames = frames
        self._swing = 0

    def half_cycle(self, stride=0.0, strafe=0.0, turn=0.0):
        """Frames for one half cycle.

        stride/strafe: mm the body travels forward/left in this half cycle.
        turn: degrees the body yaws left in this half cycle.
        """
        yaw = math.radians(turn)
        swing = _PAIRS[self._swing]
        start = [list(p) for p in self.feet]
        end = []
        for leg, (nx, ny, nz) in enumerate(self.neutral):
            # How far a planted foot slides in the body frame while the body moves.
            dx = stride - yaw * ny
            dy = strafe + yaw * nx
            half = 0.5 if leg in swing else -0.5
            end.append([nx + dx * half, ny + dy * half, nz])

        frames = []
        for k in range(1, self.frames + 1):
            u = k / self.frames
            frame = []
            for leg in range(4):
                p = _lerp(start[leg], end[leg], u)
                if leg in swing:
                    p[2] += self.lift * math.sin(math.pi * u)
                frame.append(p)
            frames.append(frame)

        self.feet = end
        self._swing ^= 1
        return frames

    def settle(self):
        """Frames that bring every foot back to neutral."""
        return self.half_cycle() + self.half_cycle()


def reposition(start, target, lift=20):
    """Move feet from ``start`` to ``target`` one leg at a time (lift, move,
    lower), for getting into and out of a gait without dragging feet."""
    feet = [list(p) for p in start]
    frames = []
    for leg in range(4):
        if all(abs(a - b) < 1 for a, b in zip(feet[leg], target[leg])):
            continue
        up = list(feet[leg])
        up[2] += lift
        frames.append(feet[:leg] + [up] + feet[leg + 1:])
        over = list(target[leg])
        over[2] += lift
        frames.append(feet[:leg] + [over] + feet[leg + 1:])
        feet[leg] = list(target[leg])
        frames.append([list(p) for p in feet])
    return frames
