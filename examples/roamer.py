"""
Wander around the house on his own, taking a photo at every stop, and come
back with a report of what he saw — optionally stopping early when he spots
something he was sent to look for.

Roamer holds the patrol itself and takes its senses as callables, like
seeker.Seeker, so it doesn't care where frames or distances come from:

    look()                   -> path of a fresh camera frame
    describe(image, target)  -> View
    distance()               -> cm to the nearest thing ahead, or None
    halt()                   -> a reason to stop now ("battery", "stopped"), or None

Each stop: look, describe, then move — a few steps forward while the sonar
and the frame say the way is clear, a turn toward open floor when they
don't. The sonar only sees straight ahead at body height, so the vision
model is also asked for stairs and edges, which the sonar can't see.

SceneDescriber (OpenAI vision) is the describe() the robot uses, and also
writes the closing report. See 26_roam.py for a standalone run and
VoiceActiveCrawler.roam for the service.
"""
import base64
import json
import os
import random
import shutil
import time
from dataclasses import dataclass, field


@dataclass
class View:
    note: str = ""             # what is in the frame, one sentence in Spanish
    notable: bool = False      # worth a photo in the report
    found: bool = False        # the target is in frame (always False without one)
    clear: str = "center"      # where the floor is open: left / center / right / none
    hazard: bool = False       # stairs, a drop or an edge ahead


@dataclass
class Stop:
    note: str
    heading: float             # nominal degrees turned left since the start
    image: str = None          # kept copy of the frame, when photo_dir is set
    notable: bool = False
    found: bool = False


@dataclass
class Tour:
    stops: list = field(default_factory=list)
    found: bool = False
    reason: str = "done"       # found / time / battery / stopped / done

    @property
    def photos(self):
        """Frames worth sending: the notable ones, or the last one if none were."""
        kept = [s.image for s in self.stops if s.image and (s.notable or s.found)]
        if not kept and self.stops and self.stops[-1].image:
            kept = [self.stops[-1].image]
        return kept


class Roamer:
    def __init__(self, crawler, look, describe, distance=lambda: None, halt=lambda: None,
                 photo_dir=None, clear_cm=35, steps=3, turn_angle=90, veer_angle=45,
                 wander=0.25, max_stops=30, speed=60, rng=None):
        self.crawler = crawler
        self.look = look
        self.describe = describe
        self.distance = distance
        self.halt = halt
        self.photo_dir = photo_dir
        self.clear_cm = clear_cm         # sonar reading under this counts as blocked
        self.steps = steps               # forward steps per stop when the way is clear
        self.turn_angle = turn_angle     # turn away from a wall or a hazard
        self.veer_angle = veer_angle     # turn toward open floor off to one side
        self.wander = wander             # chance of a random veer on a clear stop, so he doesn't pace one line
        self.max_stops = max_stops
        self.speed = speed
        self.rng = rng or random.Random()
        self._heading = 0.0

    def roam(self, target=None, minutes=10):
        """Patrol for up to ``minutes`` (or max_stops stops). With a target,
        stop as soon as it is in frame."""
        if self.photo_dir:
            os.makedirs(self.photo_dir, exist_ok=True)
        self._heading = 0.0
        tour = Tour()
        deadline = time.monotonic() + minutes * 60
        for n in range(self.max_stops):
            reason = self.halt()
            if reason:
                tour.reason = reason
                break
            if time.monotonic() >= deadline:
                tour.reason = "time"
                break
            view, image = self._see(target, n)
            tour.stops.append(Stop(view.note, self._heading, image, view.notable, view.found))
            if view.found:
                tour.found, tour.reason = True, "found"
                break
            self._move(view)
        return tour

    def _see(self, target, n):
        try:
            frame = self.look()
            view = self.describe(frame, target)
        except Exception as e:
            print(f"(no pude ver: {e})")
            return View(clear="none"), None   # blind: turn rather than walk into something
        return view, self._keep(frame, n)

    def _keep(self, frame, n):
        # look() reuses one path, so copy each frame out before the next one lands on it
        if not self.photo_dir:
            return None
        path = os.path.join(self.photo_dir, f"{n:02d}.jpg")
        try:
            shutil.copyfile(frame, path)
        except OSError as e:
            print(f"(no pude guardar la foto: {e})")
            return None
        return path

    def _move(self, view):
        d = self.distance()
        blocked = view.hazard or view.clear == "none" or (d is not None and d < self.clear_cm)
        if blocked:
            side = view.clear if view.clear in ("left", "right") else self.rng.choice(("left", "right"))
            self._turn(side, self.turn_angle)
            return
        if view.clear in ("left", "right"):
            self._turn(view.clear, self.veer_angle)
        elif self.rng.random() < self.wander:
            self._turn(self.rng.choice(("left", "right")), self.veer_angle)
        self._walk()

    def _walk(self):
        for _ in range(self.steps):
            d = self.distance()
            if d is not None and d < self.clear_cm:
                return
            self.crawler.do_action("forward", 1, self.speed)

    def _turn(self, side, angle):
        self.crawler.turn_angle(angle, side, speed=self.speed)
        self._heading = (self._heading + (angle if side == "left" else -angle)) % 360


class SceneDescriber:
    """OpenAI vision for Roamer: describe(image, target) -> View, and
    report(tour, target) -> the closing summary in Petronilo's voice."""

    URL = "https://api.openai.com/v1/chat/completions"
    PROMPT = (
        "You are the eyes of a small walking robot, camera about 10 cm off the floor, patrolling a "
        "house while the owner is away.{target} Answer only with JSON: "
        '{{"note": "<one short sentence in Spanish: what you see and where you seem to be>", '
        '"notable": true|false, "found": true|false, '
        '"clear": "left"|"center"|"right"|"none", "hazard": true|false}}. '
        "notable: a person, a pet, an open door or window, water, something fallen, broken or out of "
        "place; not plain furniture or an empty floor. "
        "found: the thing being looked for is clearly in the frame (false if nothing is being looked for). "
        "clear: where the floor ahead is open enough to walk (center = middle third; none = blocked). "
        "hazard: stairs going down, a drop, the edge of a table or a bed, a cable to trip on."
    )
    TARGET = " It is also looking for: {target}."
    REPORT = (
        "Eres Petronilo, un robot araña chilango, tío buena onda de la familia. Acabas de dar una vuelta "
        "por la casa mientras el dueño no está y le escribes por Telegram lo que viste. En español, "
        "corto (tres a cinco frases), sin markdown ni listas, con tu humor pero claro: primero lo que "
        "importa (personas, mascotas, algo raro o fuera de lugar), luego lo demás en una frase. "
        "No inventes nada que no esté en las notas.{target}\n\n"
        "Cómo terminó la vuelta: {reason}.\nNotas de cada parada, en orden:\n{notes}"
    )
    REPORT_TARGET = " Te mandaron a buscar: {target}; di si lo encontraste y dónde."
    REASONS = {
        "found": "encontraste lo que buscabas",
        "time": "se acabó el tiempo",
        "battery": "se te estaba acabando la pila",
        "stopped": "te pidieron que pararas",
        "done": "diste todas las paradas",
    }

    def __init__(self, api_key, model="gpt-4.1-mini", timeout=30):
        import requests   # here, so Roamer runs (and is testable) without it
        self._session = requests.Session()
        self._api_key = api_key
        self.model = model
        self.timeout = timeout

    def __call__(self, image_path, target=None):
        with open(image_path, "rb") as f:
            image = base64.b64encode(f.read()).decode()
        prompt = self.PROMPT.format(target=self.TARGET.format(target=target) if target else "")
        answer = json.loads(self._chat([
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "low"}},
        ], json_mode=True))
        return View(
            note=answer.get("note", ""),
            notable=bool(answer.get("notable")),
            found=bool(target) and bool(answer.get("found")),
            clear=answer.get("clear", "center"),
            hazard=bool(answer.get("hazard")),
        )

    def report(self, tour, target=None):
        notes = "\n".join(f"- {s.note}" for s in tour.stops if s.note)
        if not notes:
            return "Di la vuelta pero no pude ver nada, mijo: algo trae la cámara o el internet."
        prompt = self.REPORT.format(
            target=self.REPORT_TARGET.format(target=target) if target else "",
            reason=self.REASONS.get(tour.reason, tour.reason), notes=notes)
        return self._chat(prompt).strip()

    def _chat(self, content, json_mode=False):
        body = {"model": self.model, "messages": [{"role": "user", "content": content}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = self._session.post(self.URL, headers={"Authorization": f"Bearer {self._api_key}"},
                               json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
