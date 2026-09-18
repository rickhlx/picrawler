"""Keyboard-driven trot: diagonal legs step together, much faster than the
crawl gaits in 2_keyboard_control.py.

  W / S  : faster forward / backward (press repeatedly)
  A / D  : turn left / right
  Q / E  : strafe left / right
  Space  : stop in place
  Ctrl+C : quit (feet settle, then sit)

--level holds the body flat with an MPU6050 while trotting
(see 21_imu_check.py). --max-dps raises the servo speed cap for faster
servos; leave it at the default on the stock ones.
"""
import argparse
import threading
import time

import readchar

from picrawler import Picrawler
from picrawler import body, gait

STRIDE_STEP = 10   # mm per key press
STRIDE_MAX = 40    # mm per half cycle
TURN_STEP = 5      # degrees per key press
TURN_MAX = 15
STRAFE_STEP = 10
STRAFE_MAX = 30

parser = argparse.ArgumentParser()
parser.add_argument("--speed", type=int, default=100)
parser.add_argument("--frames", type=int, default=4, help="frames per half cycle")
parser.add_argument("--lift", type=int, default=15, help="swing height in mm")
parser.add_argument("--max-dps", type=float)
parser.add_argument("--level", action="store_true")
parser.add_argument("--axes", default="x,y,z")
args = parser.parse_args()

command = {"stride": 0.0, "turn": 0.0, "strafe": 0.0}
running = True


def clamp(value, limit):
    return max(-limit, min(limit, value))


def read_keys():
    global running
    while running:
        key = readchar.readkey().lower()
        if key == "w":
            command["stride"] = clamp(command["stride"] + STRIDE_STEP, STRIDE_MAX)
        elif key == "s":
            command["stride"] = clamp(command["stride"] - STRIDE_STEP, STRIDE_MAX)
        elif key == "a":
            command["turn"] = clamp(command["turn"] + TURN_STEP, TURN_MAX)
        elif key == "d":
            command["turn"] = clamp(command["turn"] - TURN_STEP, TURN_MAX)
        elif key == "q":
            command["strafe"] = clamp(command["strafe"] + STRAFE_STEP, STRAFE_MAX)
        elif key == "e":
            command["strafe"] = clamp(command["strafe"] - STRAFE_STEP, STRAFE_MAX)
        elif key == " ":
            command.update(stride=0.0, turn=0.0, strafe=0.0)
        elif key == readchar.key.CTRL_C:
            running = False


attitude = leveler = None
if args.level:
    from picrawler.balance import Leveler
    from picrawler.imu import MPU6050, Attitude
    imu = MPU6050(axes=args.axes.split(","))
    print("Keep the robot still: calibrating gyro...")
    imu.calibrate()
    attitude = Attitude(imu)
    leveler = Leveler(limit=6)  # more than this and lifted feet hit the shoulder limit

crawler = Picrawler(max_dps=args.max_dps)
crawler.do_action("stand", speed=60)
start = [body.to_body(i, c) for i, c in enumerate(crawler.current_step_all_leg_value())]
for frame in gait.reposition(start, gait.NEUTRAL):
    crawler.do_step(body.to_step(frame), speed=80)

trot = gait.Trot(lift=args.lift, frames=args.frames)
threading.Thread(target=read_keys, daemon=True).start()
print(__doc__)

roll_cmd = pitch_cmd = 0.0
last = time.monotonic()
try:
    while running:
        idle = not any(command.values())
        frames = trot.half_cycle(**command) if not idle else [trot.feet]
        for frame in frames:
            if leveler:
                roll, pitch = attitude.update()
                now = time.monotonic()
                roll_cmd, pitch_cmd = leveler.update(roll, pitch, now - last)
                last = now
            crawler.do_step(body.to_step(frame, roll_cmd, pitch_cmd), speed=args.speed)
        print(f"\rstride {command['stride']:+4.0f}  turn {command['turn']:+4.0f}  "
              f"strafe {command['strafe']:+4.0f} ", end="", flush=True)
except KeyboardInterrupt:
    pass
finally:
    running = False
    print()
    for frame in trot.settle():
        crawler.do_step(body.to_step(frame), speed=args.speed)
    for frame in gait.reposition(gait.NEUTRAL, start):
        crawler.do_step(body.to_step(frame), speed=80)
    crawler.do_step("sit", speed=40)
