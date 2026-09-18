"""MPU6050 (and register-compatible MPU6500/9250) IMU on the Robot HAT I2C bus,
plus a complementary filter that turns it into roll and pitch.

Wire the breakout to the HAT's I2C header (3V3, GND, SDA, SCL). Readings are
in the body frame (REP-103: x forward, y left, z up). If the chip isn't
mounted that way round, pass ``axes`` saying which chip axis lies along each
body axis, e.g. ``("-y", "x", "z")`` when the chip's -y points forward.
"""
import math
import struct
import time

from robot_hat import I2C

_SMPLRT_DIV = 0x19
_CONFIG = 0x1A
_GYRO_CONFIG = 0x1B
_ACCEL_CONFIG = 0x1C
_ACCEL_XOUT_H = 0x3B
_PWR_MGMT_1 = 0x6B
_WHO_AM_I = 0x75

_ACCEL_LSB_PER_G = 16384.0  # +/-2 g range
_GYRO_LSB_PER_DPS = 131.0   # +/-250 dps range


def _parse_axis(spec):
    sign = -1 if spec.startswith("-") else 1
    return "xyz".index(spec.lstrip("+-")), sign


class MPU6050:
    ADDRESS = 0x68

    def __init__(self, address=ADDRESS, bus=1, axes=("x", "y", "z")):
        self._i2c = I2C(address, bus=bus)
        self._axes = [_parse_axis(a) for a in axes]
        self._gyro_bias = (0.0, 0.0, 0.0)
        if self._i2c.mem_read(1, _WHO_AM_I) is False:
            raise OSError("no IMU answering at I2C address 0x%02X" % address)
        self._i2c.mem_write(0x01, _PWR_MGMT_1)    # wake, clock from gyro PLL
        self._i2c.mem_write(0x04, _SMPLRT_DIV)    # 1 kHz / (1 + 4) = 200 Hz
        self._i2c.mem_write(0x03, _CONFIG)        # DLPF ~44 Hz: cuts servo buzz
        self._i2c.mem_write(0x00, _GYRO_CONFIG)
        self._i2c.mem_write(0x00, _ACCEL_CONFIG)
        time.sleep(0.05)

    def _remap(self, v):
        return tuple(sign * v[i] for i, sign in self._axes)

    def _read_raw(self):
        data = self._i2c.mem_read(14, _ACCEL_XOUT_H)
        if data is False:
            raise OSError("IMU read failed")
        ax, ay, az, _temp, gx, gy, gz = struct.unpack(">7h", bytes(data))
        accel = tuple(a / _ACCEL_LSB_PER_G for a in (ax, ay, az))
        gyro = tuple(g / _GYRO_LSB_PER_DPS for g in (gx, gy, gz))
        return self._remap(accel), self._remap(gyro)

    def calibrate(self, samples=200):
        """Measure gyro bias. The robot must be still while this runs."""
        sums = [0.0, 0.0, 0.0]
        for _ in range(samples):
            _, gyro = self._read_raw()
            sums = [s + g for s, g in zip(sums, gyro)]
            time.sleep(0.005)
        self._gyro_bias = tuple(s / samples for s in sums)

    def read(self):
        """((ax, ay, az) in g, (gx, gy, gz) in deg/s), body frame."""
        accel, gyro = self._read_raw()
        return accel, tuple(g - b for g, b in zip(gyro, self._gyro_bias))


class Attitude:
    """Complementary filter: gyro for fast changes, gravity for drift.

    ``alpha`` near 1 trusts the gyro more, which rides through the jolts of
    walking better; lower it if the estimate drifts.
    """

    def __init__(self, imu, alpha=0.98):
        self.imu = imu
        self.alpha = alpha
        self.roll = 0.0
        self.pitch = 0.0
        self._last = None

    def update(self):
        """Read the IMU once and return (roll, pitch) in degrees."""
        (ax, ay, az), (gx, gy, _gz) = self.imu.read()
        now = time.monotonic()
        acc_roll = math.degrees(math.atan2(ay, az))
        acc_pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az)))
        if self._last is None:
            self.roll, self.pitch = acc_roll, acc_pitch
        else:
            dt = now - self._last
            a = self.alpha
            self.roll = a * (self.roll + gx * dt) + (1 - a) * acc_roll
            self.pitch = a * (self.pitch + gy * dt) + (1 - a) * acc_pitch
        self._last = now
        return self.roll, self.pitch
