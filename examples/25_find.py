"""
Look around for an object with the camera and walk up to it, stopping short
with the ultrasonic sensor (trigger D2, echo D3). Needs OPENAI_API_KEY in
secret.py; frames go to a small vision model.

    sudo python3 25_find.py "red cup"
    sudo python3 25_find.py "la pelota" --stop-cm 20

Stop petronilo.service first: it holds the camera.
"""
import argparse

from picamera2 import Picamera2
from picrawler import Picrawler
from secret import OPENAI_API_KEY
from seeker import Seeker, Sonar, VisionLocator

FRAME = "/tmp/picrawler_find.jpeg"

ap = argparse.ArgumentParser()
ap.add_argument("target", help="what to look for, e.g. 'red cup'")
ap.add_argument("--stop-cm", type=float, default=15, help="stop this close to what is ahead")
ap.add_argument("--turns", type=int, default=12, help="turns to scan before giving up")
ap.add_argument("--model", default="gpt-4.1-mini")
args = ap.parse_args()

camera = Picamera2()
camera.configure(camera.create_still_configuration(main={"size": (1024, 768)}))
camera.start()


def look():
    camera.capture_file(FRAME)
    return FRAME


crawler = Picrawler()
seeker = Seeker(crawler, look, VisionLocator(OPENAI_API_KEY, model=args.model), Sonar(),
                scan_turns=args.turns, stop_cm=args.stop_cm)
try:
    crawler.do_action("stand", speed=50)
    print(seeker.seek(args.target))
except KeyboardInterrupt:
    print("\nStop.")
finally:
    camera.stop()
    crawler.do_action("sit", speed=50)
