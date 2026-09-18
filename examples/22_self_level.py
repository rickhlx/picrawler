"""Stand and keep the body level while the surface under it tilts.

Put the robot on a board and tilt the board slowly: the legs extend and
retract to hold the body flat. Needs an MPU6050 (see 21_imu_check.py).
"""
import argparse
import time

from picrawler import Picrawler
from picrawler import body, gait
from picrawler.balance import Leveler
from picrawler.imu import MPU6050, Attitude

parser = argparse.ArgumentParser()
parser.add_argument("--axes", default="x,y,z")
parser.add_argument("--gain", type=float, default=3.0)
args = parser.parse_args()

imu = MPU6050(axes=args.axes.split(","))
print("Keep the robot still: calibrating gyro...")
imu.calibrate()
attitude = Attitude(imu)
leveler = Leveler(gain=args.gain)

crawler = Picrawler()
crawler.do_action("stand", speed=60)
start = [body.to_body(i, c) for i, c in enumerate(crawler.current_step_all_leg_value())]
for frame in gait.reposition(start, gait.NEUTRAL):
    crawler.do_step(body.to_step(frame), speed=80)

last = time.monotonic()
try:
    while True:
        roll, pitch = attitude.update()
        now = time.monotonic()
        leveler.update(roll, pitch, now - last)
        last = now
        crawler.do_step(body.to_step(gait.NEUTRAL, leveler.roll, leveler.pitch), speed=100)
        print(f"\rtilt {roll:+5.1f} {pitch:+5.1f}  correction {leveler.roll:+5.1f} {leveler.pitch:+5.1f} ",
              end="", flush=True)
except KeyboardInterrupt:
    print()
finally:
    crawler.do_step(body.to_step(gait.NEUTRAL), speed=60)
    for frame in gait.reposition(gait.NEUTRAL, start):
        crawler.do_step(body.to_step(frame), speed=80)
    crawler.do_step("sit", speed=40)
