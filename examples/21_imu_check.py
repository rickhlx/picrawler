"""Print roll and pitch from an MPU6050 so you can check its mounting.

Wire the MPU6050 to the Robot HAT I2C header, run this with the robot flat,
then check the signs:
  - lift the LEFT side  -> roll goes positive
  - tip the NOSE down   -> pitch goes positive
If an axis is swapped or backwards, pass --axes naming the chip axis that
lies along the robot's forward, left and up directions, e.g. --axes -y,x,z,
and use the same value for 22_self_level.py and 23_trot.py.
"""
import argparse
import time

from picrawler.imu import MPU6050, Attitude

parser = argparse.ArgumentParser()
parser.add_argument("--axes", default="x,y,z")
args = parser.parse_args()

imu = MPU6050(axes=args.axes.split(","))
print("Keep the robot still: calibrating gyro...")
imu.calibrate()
attitude = Attitude(imu)

try:
    while True:
        roll, pitch = attitude.update()
        (ax, ay, az), _ = imu.read()
        print(f"\rroll {roll:+6.1f}  pitch {pitch:+6.1f}  |  accel {ax:+.2f} {ay:+.2f} {az:+.2f} g ",
              end="", flush=True)
        time.sleep(0.05)
except KeyboardInterrupt:
    print()
