"""
Wander around on his own, photograph each stop and print a report of what he
saw; with a target, stop when he spots it. The ultrasonic sensor (trigger D2,
echo D3) and the camera keep him off walls and stairs. Needs OPENAI_API_KEY
in secret.py; frames go to a small vision model.

    sudo python3 26_roam.py
    sudo python3 26_roam.py --minutes 3 --target "las llaves"

Stop petronilo.service first: it holds the camera. Photos land in --photos.
"""
import argparse

from picamera2 import Picamera2
from picrawler import Picrawler
from roamer import Roamer, SceneDescriber
from secret import OPENAI_API_KEY
from seeker import Sonar

FRAME = "/tmp/picrawler_roam.jpeg"

ap = argparse.ArgumentParser()
ap.add_argument("--minutes", type=float, default=5)
ap.add_argument("--target", default=None, help="stop when this is in sight, e.g. 'el gato'")
ap.add_argument("--stops", type=int, default=30)
ap.add_argument("--photos", default="/tmp/picrawler_roam")
ap.add_argument("--model", default="gpt-4.1-mini")
args = ap.parse_args()

camera = Picamera2()
camera.configure(camera.create_still_configuration(main={"size": (1024, 768)}))
camera.start()


def look():
    camera.capture_file(FRAME)
    return FRAME


eyes = SceneDescriber(OPENAI_API_KEY, model=args.model)
crawler = Picrawler()
roamer = Roamer(crawler, look, eyes, Sonar(), photo_dir=args.photos, max_stops=args.stops)
try:
    crawler.do_action("stand", speed=50)
    tour = roamer.roam(args.target, args.minutes)
    for stop in tour.stops:
        print(f"{stop.heading:5.0f}°  {'*' if stop.notable else ' '} {stop.note}")
    print(f"\n({tour.reason}) {eyes.report(tour, args.target)}")
    print("photos:", ", ".join(tour.photos) or "none")
except KeyboardInterrupt:
    print("\nStop.")
finally:
    camera.stop()
    crawler.do_action("sit", speed=50)
