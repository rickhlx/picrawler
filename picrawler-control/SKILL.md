---
name: picrawler-control
description: "Control a SunFounder PiCrawler quadruped robot: walk, turn, pose, sense, play sounds, camera vision."
homepage: https://docs.sunfounder.com/projects/pi-crawler/en/latest/
metadata:
  openclaw:
    emoji: "🦾"
    requires:
      bins: ["python3"]
      python: ["picrawler", "robot_hat", "vilib"]
    install:
      - id: robot-hat
        kind: shell
        cmd: |
          cd ~ && git clone -b 2.5.x https://github.com/rickhlx/robot-hat.git && cd robot-hat && sudo python3 install.py
      - id: picrawler
        kind: shell
        cmd: |
          cd ~ && git clone https://github.com/rickhlx/picrawler.git && sudo pip3 install ~/picrawler --break-system-packages
      - id: vilib
        kind: shell
        cmd: |
          cd ~ && git clone https://github.com/sunfounder/vilib.git --depth 1 && cd vilib && sudo python3 install.py
      - id: i2s-sound
        kind: shell
        cmd: |
          cd ~/robot-hat && sudo bash i2samp.sh
---

# PiCrawler Control Skill

You are controlling a **PiCrawler** quadruped robot — a Raspberry Pi with 12 metal-gear servos, ultrasonic sensor, PiCamera, and speaker.

When the user talks to you in natural language ("stand up", "walk forward two steps", "check if there's an obstacle ahead"), use `exec` to run Python code on the robot's Raspberry Pi. Examples below show exactly what to exec.

## Safety Rules — Always Follow These

1. **Stand before move**: Always call `do_step('stand', 40)` first, then `sleep(1)`, before any movement.
2. **Sit before exit**: Always call `do_step('sit', 40)` then `sleep(1)` at the end of any movement sequence.
3. **Speed range**: 20–50 for careful/test, 60–80 for normal, 100 max.
4. **Start slow**: If unsure, use speed=40 and step=1.
5. **Flat surface**: Only run on flat ground.
6. **Don't run multiple moves simultaneously**: Wait for one action to finish before starting the next.

## Recognition Mapping — What the User Said → What You Run

| User says... | You should exec... |
|---|---|
| "stand up" | `do_step('stand', 40) + sleep(1)` |
| "sit down" | `do_step('sit', 40) + sleep(1)` |
| "go forward / move ahead / walk forward" | `stand → do_action('forward', 1-3, 60) → sit` |
| "go back / move backward / walk backward" | `stand → do_action('backward', 1-3, 60) → sit` |
| "turn left" | `stand → do_action('turn left', 1, 60) → sit` |
| "turn right" | `stand → do_action('turn right', 1, 60) → sit` |
| "slight turn / adjust angle" | `stand → do_action('turn left angle', 1, 60) or turn right angle → sit` |
| "do a push-up" | `stand → do_step(push_up pose arrays) → sit` |
| "wave" | `stand → mix_step to lift one front leg → sit` |
| "bow / nod / shake your head / dance / hula / bounce / spin / play dead / high five" | `trick('bow')` etc. → sit (see Tricks) |
| "is there something ahead / measure distance" | `exec sensor distance read, return the value to user` |
| "make a sound / speak" | `music.sound_play(path) or music.music_play(path)` |
| "take a photo / take a picture" | `Vilib.take_photo() → tell user where it saved` |
| "look at me / detect faces" | `Vilib.face_detect_switch(True) → read result → tell user` |
| "find red / find blue / locate color..." | `Vilib.color_detect('red') → read coordinates → tell user` |

Response style: When you successfully execute a command, briefly tell the user what happened in a friendly tone. e.g. "Standing up now 🦾" or "Walked forward two steps, now sitting down" or "There's an obstacle 23 cm ahead."

## exec Code Templates

### Basic Movement (EXEC THIS)

```python
from picrawler import Picrawler
from time import sleep
c = Picrawler()
try:
    c.do_step('stand', 40)
    sleep(1.0)
    c.do_action('forward', 2, 60)   # <-- swap action, steps, speed here
finally:
    c.do_step('sit', 40)
    sleep(1.0)
```

Available action names: `forward`, `backward`, `turn left`, `turn right`, `turn left angle`, `turn right angle`

### Tricks (EXEC THIS)

Tricks stand up and return to the stand pose on their own; sit afterwards.

```python
from picrawler import Picrawler
from time import sleep
c = Picrawler()
try:
    c.trick('play dead')   # <-- swap trick name here
finally:
    c.do_step('sit', 40)
    sleep(1.0)
```

Available tricks: `bow`, `nod`, `shake head`, `shimmy` (dance), `hula`, `bounce`, `spin`, `play dead`, `high five`

### Stand or Sit Only (use when no movement follows)

```python
from picrawler import Picrawler
from time import sleep
c = Picrawler()
c.do_step('stand', 40)  # or 'sit'
sleep(1.0)
```

### Read Ultrasonic Distance

```python
from robot_hat import Pin, Ultrasonic
s = Ultrasonic(Pin("D2"), Pin("D3"))
d = s.read()
print(f"{d:.1f}" if d else "None")
```

Parse `stdout` from exec output to get the distance value.

### Play Sound Effects

```python
from robot_hat import Music
m = Music()
m.music_set_volume(50)
m.sound_play('/home/ricardo/picrawler/examples/sounds/talk1.wav')
```

Other available sound effects: `sign.wav`, `talk3.wav`. Music files are in `/home/ricardo/picrawler/examples/musics/`.

### Take a Photo

```python
from vilib import Vilib
from time import strftime, localtime
Vilib.camera_start(vflip=False, hflip=False)
Vilib.display(local=True, web=True)
sleep(1)
name = f"photo_{strftime('%Y-%m-%d-%H-%M-%S', localtime())}"
Vilib.take_photo(name, '/home/ricardo/Pictures/')
Vilib.camera_close()
print(f"saved: /home/ricardo/Pictures/{name}.jpg")
```

### Detect Faces / Colors

```python
from vilib import Vilib
from time import sleep
Vilib.camera_start(vflip=False, hflip=False)
Vilib.display(local=True, web=True)
sleep(1)
Vilib.face_detect_switch(True)
# or Vilib.color_detect('red')
sleep(2)
n = Vilib.detect_obj_parameter.get('human_n', 0)
if n > 0:
    x = Vilib.detect_obj_parameter.get('human_x')
    y = Vilib.detect_obj_parameter.get('human_y')
    print(f"Detected {n} face(s), center at ({x}, {y})")
else:
    print("No faces detected")
Vilib.camera_close()
```

## Typical Conversation Flow

**User:** "stand up"
**AI executes:** the "Stand or Sit Only" template above
**AI replies:** "Standing up now 🦾"

**User:** "walk forward three steps"
**AI executes:** the "Basic Movement" template, replacing `forward` and `2, 60` with `forward`, `3`, `60`
**AI replies:** "Walked forward three steps, now sitting down"

**User:** "check if there's something ahead"
**AI executes:** the "Read Ultrasonic Distance" template
**AI replies:** "There's an obstacle about 23 cm ahead" / "The path is clear ahead"

## Full API Reference

See `references/api.md` for all available methods:
- `do_single_leg(leg, coodinate, speed)` — move one leg
- `mix_step(base, leg, coodinate)` — create custom poses
- `add_action(name, steps)` — register custom multi-step action
- `trick(name)` — crowd-pleaser tricks (bow, shimmy, play dead, ...)
- `move_list` keys: forward, backward, turn_left, turn_right, turn_left_angle, turn_right_angle, push_up, wave, look_left, look_right, look_up, look_down
- `Vilib` gesture/traffic_sign/QR code detection
- `Music` TTS and background music

## Helper Script (Optional)

There's also a CLI convenience script at `scripts/pc.py` — same functions, but prefer direct Python inline via exec for more control.
