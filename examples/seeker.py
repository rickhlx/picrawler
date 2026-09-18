"""
Find an object with the camera and walk up to it, using the ultrasonic
sensor to stop short of whatever is in front.

Seeker holds the search itself and takes its senses as callables, so it
doesn't care where frames or distances come from:

    look()                   -> path of a fresh camera frame
    locate(image, target)    -> Sighting
    distance()               -> cm to the nearest thing ahead, or None

VisionLocator (OpenAI vision) and Sonar (robot_hat.Ultrasonic) are the
implementations the robot uses. See 25_find.py for a standalone run and
VoiceActiveCrawler.find for the "find <object>" voice action.
"""
import base64
import json
import time
from dataclasses import dataclass

import requests


@dataclass
class Sighting:
    found: bool
    position: str = "center"   # left / center / right in the frame
    size: str = "small"        # small / medium / large: how much of the frame it fills
    note: str = ""


@dataclass
class Result:
    found: bool
    near: bool = False         # stopped next to it (sonar or it fills the frame)
    distance: float = None     # cm, last sonar reading when it stopped
    note: str = ""


class Seeker:
    def __init__(self, crawler, look, locate, distance=lambda: None,
                 scan_turns=12, turn_angle=30, nudge_angle=15,
                 stop_cm=15, max_steps=8, speed=60):
        self.crawler = crawler
        self.look = look
        self.locate = locate
        self.distance = distance
        self.scan_turns = scan_turns     # 12 x 30 deg nominal; feet slip, so a bit short of a full turn
        self.turn_angle = turn_angle
        self.nudge_angle = nudge_angle
        self.stop_cm = stop_cm
        self.max_steps = max_steps
        self.speed = speed

    def seek(self, target):
        sighting = self._scan(target)
        if not sighting:
            return Result(found=False)
        return self._approach(target, sighting)

    def _scan(self, target):
        for _ in range(self.scan_turns):
            sighting = self._sight(target)
            if sighting.found:
                return sighting
            self._turn("left", self.turn_angle)
        return None

    def _approach(self, target, sighting):
        d = None
        for _ in range(self.max_steps):
            self._center(sighting)
            if sighting.size == "large":
                return Result(found=True, near=True, distance=d, note=sighting.note)
            d = self.distance()
            if d is not None and d <= self.stop_cm:
                return Result(found=True, near=True, distance=d, note=sighting.note)
            self.crawler.do_action("forward", 1, self.speed)
            sighting = self._sight(target)
            if not sighting.found:
                # lost it walking up; one more look after a short pause
                time.sleep(0.3)
                sighting = self._sight(target)
                if not sighting.found:
                    return Result(found=True, near=False, distance=d)
        return Result(found=True, near=False, distance=self.distance(), note=sighting.note)

    def _center(self, sighting):
        if sighting.position in ("left", "right"):
            self._turn(sighting.position, self.nudge_angle)

    def _sight(self, target):
        try:
            return self.locate(self.look(), target)
        except Exception as e:
            print(f"(no pude ver: {e})")
            return Sighting(found=False)

    def _turn(self, side, angle):
        moves = self.crawler.move_list
        saved, moves.angle = moves.angle, angle
        try:
            self.crawler.do_action(f"turn {side} angle", 1, self.speed)
        finally:
            moves.angle = saved


class VisionLocator:
    """Asks an OpenAI vision model whether target is in a frame, and where."""

    URL = "https://api.openai.com/v1/chat/completions"
    PROMPT = (
        "You are the eyes of a small walking robot looking for: {target}. "
        "Is it visible in this camera frame? Answer only with JSON: "
        '{{"found": true|false, "position": "left"|"center"|"right", '
        '"size": "small"|"medium"|"large", "note": "<few words in Spanish on where it is>"}}. '
        "position is where it sits horizontally in the frame (center = middle third). "
        "size is how much of the frame it fills (large = more than a third, so the robot is next to it). "
        "Say found only if you are fairly sure it is that object."
    )

    def __init__(self, api_key, model="gpt-4.1-mini", timeout=20):
        self._api_key = api_key
        self.model = model
        self.timeout = timeout

    def __call__(self, image_path, target):
        with open(image_path, "rb") as f:
            image = base64.b64encode(f.read()).decode()
        r = requests.post(
            self.URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self.model,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": self.PROMPT.format(target=target)},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "low"}},
                ]}],
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        answer = json.loads(r.json()["choices"][0]["message"]["content"])
        return Sighting(
            found=bool(answer.get("found")),
            position=answer.get("position", "center"),
            size=answer.get("size", "small"),
            note=answer.get("note", ""),
        )


class Sonar:
    """Median of a few ultrasonic reads; None when nothing echoes back."""

    def __init__(self, trig="D2", echo="D3", reads=5):
        from robot_hat import Pin, Ultrasonic
        self._sonar = Ultrasonic(Pin(trig), Pin(echo))
        self.reads = reads

    def __call__(self):
        values = []
        for _ in range(self.reads):
            d = self._sonar.read()
            if d is not None and d > 0:   # -1 / -2 are echo timeouts
                values.append(d)
            time.sleep(0.03)
        if not values:
            return None
        values.sort()
        return values[len(values) // 2]
