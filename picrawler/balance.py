"""Closed-loop body leveling."""
import math


class Leveler:
    """Integral controller that tilts the body against the measured tilt.

    The body's tilt is roughly the ground's tilt plus the rotation we command
    through the legs, so integrating the error drives it to ``target``
    regardless of the slope. The servos have no feedback, so this is
    quasi-static leveling, not dynamic balance.

    ``gain`` is 1/s: 3 removes most of a step change in about a second.
    ``limit`` caps the size of the correction in degrees, in any direction.
    Standing, the uphill legs hit the shoulder servo limit past ~11 deg;
    while trotting with a 15 mm swing lift, past ~6 deg.
    """

    def __init__(self, gain=3.0, limit=10.0, deadband=0.5, target=(0.0, 0.0)):
        self.gain = gain
        self.limit = limit
        self.deadband = deadband
        self.target = target
        self.roll = 0.0
        self.pitch = 0.0

    def update(self, roll, pitch, dt):
        """Feed the measured attitude; returns the (roll, pitch) to command."""
        err_roll = roll - self.target[0]
        err_pitch = pitch - self.target[1]
        if math.hypot(err_roll, err_pitch) < self.deadband:
            return self.roll, self.pitch
        self.roll -= self.gain * err_roll * dt
        self.pitch -= self.gain * err_pitch * dt
        size = math.hypot(self.roll, self.pitch)
        if size > self.limit:
            # Scale back along the same direction; this doubles as anti-windup.
            self.roll *= self.limit / size
            self.pitch *= self.limit / size
        return self.roll, self.pitch

    def reset(self):
        self.roll = self.pitch = 0.0
