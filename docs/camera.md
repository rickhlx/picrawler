# Seeing with the camera

The camera on the front of the robot does four quite different jobs, and it
helps to know which layer you are working at:

| Layer | What it does | Where it lives |
|-------|--------------|----------------|
| `vilib` | Live stream, photos, video, face / colour / QR detection, all on the Pi | `5_display.py`, `6_record_video.py` |
| Vision games | Colour tracking that drives the legs | `7_bull_fight.py`, `8_treasure_hunt.py` |
| `Seeker` | Turn until a vision model spots something, walk to it, stop before hitting it | `seeker.py`, `25_find.py` |
| Petronilo's eyes | A frame attached to a question, `look`, `find <object>`, `where <object>` | `voice_active_crawler.py` |

**Only one process can hold the camera.** If Petronilo is running as a
service, every other camera example fails until you stop him:

```bash
sudo systemctl stop petronilo
# ... play ...
sudo systemctl start petronilo
```

## Photos, video and the live view

`5_display.py` is the sandbox. Run it and press keys:

```bash
sudo python3 ~/picrawler/examples/5_display.py
```

| Key | What happens |
|-----|--------------|
| `q` | Save a photo to `~/Pictures/` |
| `1`–`6` | Detect red, orange, yellow, green, blue, purple |
| `0` | Stop colour detection |
| `f` | Toggle face detection |
| `r` | Scan for QR codes and print what they say |
| `s` | Print what is currently detected |

Set `vflip` / `hflip` if the camera is mounted upside down — the vision model
is surprisingly tolerant of a flipped frame, but face detection is not.

`6_record_video.py` records to `~/Videos/`: `Q` starts, pauses and resumes,
`E` stops.

## Watching from a browser

`vilib` serves the live camera over HTTP on port 9000. This is the easiest way
to aim the camera, and the only practical way to see what the robot sees while
it is walking around on the floor.

| URL | What it is |
|-----|------------|
| `http://picrawler.local:9000/` | The web UI, with the detection overlays drawn on |
| `http://picrawler.local:9000/mjpg` | The raw MJPEG stream, for a browser tab, VLC or `ffplay` |

Any of the camera examples turns it on, because they all call:

```python
Vilib.camera_start(vflip=False, hflip=False)
Vilib.display(local=False, web=True)
```

`local=True` additionally opens a preview window **on the Pi's own desktop**,
which is useless on a headless robot and costs CPU — keep it `False` and use
the browser.

### Just the stream, nothing else

`examples/stream.py` does exactly that and nothing else — no legs, no voice,
no vision model:

```bash
sudo systemctl stop petronilo                     # he holds the camera
sudo python3 ~/picrawler/examples/stream.py
sudo python3 ~/picrawler/examples/stream.py --face --flip
sudo python3 ~/picrawler/examples/stream.py --color red
sudo python3 ~/picrawler/examples/stream.py --qr   # prints codes as it sees them
```

The detection flags draw their overlays into the web UI, which makes tuning
detection far less of a guessing game than reading numbers out of a terminal.
`--flip` is for a camera mounted upside down.

### Outside a browser

```bash
ffplay -fflags nobuffer http://picrawler.local:9000/mjpg
vlc http://picrawler.local:9000/mjpg
curl -s http://picrawler.local:9000/mjpg > /dev/null    # just checking it is alive
```

### Things to know

- **Petronilo holds the camera.** The stream and the assistant cannot both
  have it. Stop the service first, and remember to start it again.
- **`picrawler.local` needs mDNS**, which means the same subnet. Use the IP
  address otherwise; see [Wi-Fi](wifi.md) for finding it.
- **There is no authentication and no encryption.** Anyone on the network can
  watch. That is fine on a home LAN and is not fine port-forwarded to the
  internet — if you want it remotely, put it behind a VPN or an SSH tunnel:

  ```bash
  ssh -L 9000:localhost:9000 picrawler     # then open http://localhost:9000/
  ```

- **Streaming costs CPU and bandwidth**, and on a battery-powered robot both
  cost runtime. Turn it off when you are done looking.

## Detection you can build on

`vilib` runs the classic OpenCV detectors on the Pi itself — no network, no
API key, a few frames per second. After switching one on, results arrive in
`Vilib.detect_obj_parameter`:

```python
from vilib import Vilib

Vilib.camera_start(vflip=False, hflip=False)
Vilib.color_detect("red")                       # one colour at a time
Vilib.face_detect_switch(True)
Vilib.qrcode_detect_switch(True)

Vilib.detect_obj_parameter["color_n"]           # how many red blobs
Vilib.detect_obj_parameter["color_x"]           # blob centre, 0-640
Vilib.detect_obj_parameter["human_n"]           # faces found
Vilib.detect_obj_parameter["human_x"]           # face centre
Vilib.detect_obj_parameter["qr_data"]           # decoded text, or "None"
```

That is all `7_bull_fight.py` is: charge when `color_n` is non-zero, beep, back
off. `8_treasure_hunt.py` names a colour in Spanish and you drive the robot to
find it.

Two things worth knowing before you build on this. Colour detection is HSV
thresholding, so it follows a red cup and a red sofa equally happily, and it
falls apart under warm indoor light. Face detection finds *a* face, not *whose*
— for "is that Ricardo?" you need the vision model below.

### Recipes

**Turn to keep a face centred** — the cheapest useful behaviour, and entirely
offline:

```python
x = Vilib.detect_obj_parameter.get("human_x", 320)
if Vilib.detect_obj_parameter.get("human_n", 0):
    if x < 240:
        crawler.do_action("turn left", 1, 60)
    elif x > 400:
        crawler.do_action("turn right", 1, 60)
```

**QR codes as commands.** Print a few cards, hold one up, and act on the text
— a party trick that needs no cloud and no microphone:

```python
code = Vilib.detect_obj_parameter.get("qr_data", "None")
if code in TRICKS:
    crawler.trick(code)
```

**A photo on a schedule.** Ask Petronilo to "tómame una foto cada hora" and
the reminder fires whether or not anyone is home — see
[reminders](petronilo.md#reminders-and-tasks).

## Find something and walk to it

`Seeker` is the interesting one. It turns in place taking frames, sends each to
a small vision model, and when the model says it can see the target, walks
towards it and stops on the ultrasonic sensor:

```bash
sudo python3 ~/picrawler/examples/25_find.py "red cup"
sudo python3 ~/picrawler/examples/25_find.py "la pelota" --stop-cm 20 --turns 8
```

It prints a `Result(found=..., near=..., distance=..., note=...)`. Defaults:
twelve 30° turns before giving up, stop at 15 cm or when the object fills the
frame, at most eight forward steps.

`Seeker` takes its senses as plain callables, so nothing in it is tied to this
robot's hardware:

```python
Seeker(crawler,
       look,                                  # -> path to a fresh frame
       VisionLocator(OPENAI_API_KEY),         # (image, target) -> Sighting
       Sonar())                               # -> cm ahead, or None
```

Swap `VisionLocator` for a local model, or `Sonar` for a lambda returning
`None`, and the search still works. If you want to test the search logic
without a robot at all, pass stubs for all three.

The feet slip on hard floors, so twelve 30° turns is a bit short of a full
circle by design — run the scan twice rather than trusting one sweep.

## Petronilo's eyes

He uses the camera four ways, and only the first is automatic.

**A frame with your question.** When what you say sounds visual — "¿qué ves?",
"¿quién está aquí?", "¿de qué color es esto?" — the code grabs a frame and
sends it with the question, so there is no extra round trip. Movement commands
that happen to contain "mira" ("mira a la izquierda") are excluded, so they
don't cost you a photo. The word list is `VISUAL_HINTS` in
`voice_active_crawler.py`; add to it if he keeps answering blind.

**The `look` tool.** The agent can decide to take a photo on its own when a
question needs one. He is told not to if the question already came with a
frame.

**`find <object>`.** "Búscame las llaves" runs the `Seeker` above on the action
thread, so the fidgets don't fight him for the servos while he walks. He says
something short first ("déjame echar un ojo, mijo"), then reports back once the
search ends — and the body waits for that sentence to finish playing before it
turns, so the narration never lands after the movement.

**`where <object>`.** "¿Dónde está el perro?" is the same sweep with the
walking left out: he turns until he sees it, stops facing it, and says which
way it is relative to how he was standing ("a tu izquierda, junto al sillón").
Use it indoors, when you want to know rather than to send a robot across the
room.

There is also `GREET_WITH_VISION = True` in
`18_voice_active_crawler_gpt.py`, which makes him look at whoever woke him and
greet them by what he sees. It is off by default: it adds about three seconds
before he starts listening, which feels like a long time when you are standing
in front of a robot.

### Things to try

- Ask him "¿qué traigo puesto?" — the frame goes with the question, and he
  will tell you, with opinions.
- Ask him to find something that isn't there. He gives up after a full scan
  and says so, which is the behaviour you want to verify before you trust him
  on the kitchen floor.
- Point him at a page of text. The vision model reads it; his prompt forbids
  reading URLs and paths aloud, so he will summarise instead.
- Set a reminder that uses the camera: `make ask MSG="revisa si dejé la
  estufa prendida"` sends a photo through the agent without anyone saying the
  wake word.

## Costs and privacy

Frames go to OpenAI (`gpt-4.1-mini` for `find`, the main model for visual
questions) only when one of the paths above fires. The `vilib` detectors never
leave the Pi. Photos taken by the voice assistant are written to
`examples/img_input.jpeg` and overwritten each time — that file is excluded
from `make sync`, so it never travels back to your computer.

The agent's daily spend cap (`AGENT_DAILY_BUDGET_USD`, $5) covers vision calls
too. `make status` shows what has been spent today.
