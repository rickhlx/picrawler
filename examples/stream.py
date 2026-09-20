"""
Serve the camera over HTTP and nothing else: no legs, no voice, no vision
model. The easiest way to aim the camera or to watch what he sees.

    sudo systemctl stop petronilo     # he holds the camera
    sudo python3 stream.py
    sudo python3 stream.py --face --flip
    sudo python3 stream.py --color red

Then open http://<pi>:9000/ for the view with the detection overlays drawn on,
or http://<pi>:9000/mjpg for the raw stream (VLC, ffplay, another program).
Remember to start the service again afterwards.
"""
import argparse
import time

from vilib import Vilib

COLORS = ("red", "orange", "yellow", "green", "blue", "purple")

ap = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--flip", action="store_true", help="camera mounted upside down")
ap.add_argument("--face", action="store_true", help="draw face detection")
ap.add_argument("--color", choices=COLORS, help="draw detection for one colour")
ap.add_argument("--qr", action="store_true", help="decode QR codes and print them")
args = ap.parse_args()

Vilib.camera_start(vflip=args.flip, hflip=args.flip)
# local=False: a preview window on the Pi's own desktop is useless on a
# headless robot and costs CPU. web=True is the part we want.
Vilib.display(local=False, web=True)

if args.face:
    Vilib.face_detect_switch(True)
if args.color:
    Vilib.color_detect(args.color)
if args.qr:
    Vilib.qrcode_detect_switch(True)

print("http://<pi>:9000/ (overlays) or http://<pi>:9000/mjpg (raw) — Ctrl+C to stop")

last_qr = None
try:
    while True:
        if args.qr:
            code = Vilib.detect_obj_parameter.get("qr_data", "None")
            if code != "None" and code != last_qr:
                last_qr = code
                print(f"QR: {code}")
        time.sleep(0.2)
except KeyboardInterrupt:
    print("\nStop.")
finally:
    Vilib.camera_close()
