"""Crowd-pleaser tricks from picrawler/tricks.py.

  sudo python3 24_tricks.py                 # every trick, one after another
  sudo python3 24_tricks.py bow "play dead" # just these, in this order
"""
import argparse
import time

from picrawler import Picrawler
from picrawler.tricks import TRICKS

parser = argparse.ArgumentParser()
parser.add_argument("names", nargs="*", metavar="trick", help="one or more of: " + ", ".join(TRICKS))
parser.add_argument("--pause", type=float, default=1.0, help="seconds between tricks")
args = parser.parse_args()
unknown = [n for n in args.names if n not in TRICKS]
if unknown:
    parser.error("unknown trick: " + ", ".join(unknown))

crawler = Picrawler()
try:
    for name in args.names or TRICKS:
        print(name)
        crawler.trick(name)
        time.sleep(args.pause)
except KeyboardInterrupt:
    pass
finally:
    crawler.do_action("sit", speed=40)
