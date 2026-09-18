# PiCrawler Python API Reference

This is the reference for programming PiCrawler directly from Python.
The OpenClaw AI agent should read this when it needs precise API signatures.

## picrawler.Picrawler

```python
from picrawler import Picrawler
crawler = Picrawler(pin_list=None, init_angles=None)
```

Resets the MCU on init (~0.2s delay). Pin list defaults to `[9,10,11, 3,4,5, 0,1,2, 6,7,8]`.

### do_action(motion_name, step=1, speed=50)

Execute a named gait action.

| motion_name | Effect |
|---|---|
| `forward` | Walk forward |
| `backward` | Walk backward |
| `turn left` | Pivot left in place |
| `turn right` | Pivot right in place |
| `turn left angle` | Small-angle turn left |
| `turn right angle` | Small-angle turn right |

Custom actions registered via `add_action()` are also callable.

The `step` parameter repeats the full sequence; `speed` is 0–100.

### do_step(_step, speed=50, israise=False)

Named poses or custom coordinate array.

| string value | Effect |
|---|---|
| `'stand'` | Stand up (from step_list) |
| `'sit'` | Sit down (from step_list) |

Or pass a list of 4 coordinate arrays:
```python
crawler.do_step([
    [x, y, z],  # Right Front leg
    [x, y, z],  # Left Front leg
    [x, y, z],  # Left Rear leg
    [x, y, z],  # Right Rear leg
], speed=60)
```

### do_single_leg(leg, coodinate=[50, 50, -33], speed=50)

Move one leg to a coordinate. `leg`: 0=RF, 1=LF, 2=LR, 3=RR.

### mix_step(basic_step, leg, coodinate=[50, 50, -33])

Replace one leg's coordinate in a base pose, return new pose array.

### add_action(action_name, action_list)

Register a custom multi-step action. `action_list` is a list of 4-coordinate arrays.

### move_list

A `dict`-like object that generates leg coordinates on access. Available keys:

| key | description |
|---|---|
| `stand` | Stand up pose |
| `sit` | Sit down pose |
| `ready` | Transition from sit to stand |
| `forward` | Walk forward sequence |
| `backward` | Walk backward sequence |
| `turn_left` | Pivot left |
| `turn_right` | Pivot right |
| `turn_left_angle` | Small left turn |
| `turn_right_angle` | Small right turn |
| `push_up` | Push-up motion |
| `wave` | Wave front leg |
| `look_left` | Rotate body left |
| `look_right` | Rotate body right |
| `look_up` | Rotate body up |
| `look_down` | Rotate body down |

Access: `crawler.move_list['forward']` returns a list of coordinate arrays.

### Constants

- `A = 48` — Upper leg length (mm)
- `B = 78` — Lower leg length (mm)
- `C = 33` — Foot-to-hip offset (mm)
- `OFFSET_FILE = '~/.config/.picrawler.config'` — Servo calibration offsets
- `PIN_LIST = [9,10,11, 3,4,5, 0,1,2, 6,7,8]` — Default servo PWM channels

### Coordinate System

Each leg uses an independent coordinate system with origin at the hip joint:

- **x**: forward/backward (positive = forward)
- **y**: left/right (positive = left for RF/RR, right for LF/LR)
- **z**: up/down (negative = down, toward ground)

Robot dimensions constrain valid coordinates:
- alpha (shoulder): -90° to 90°
- beta (knee): -10° to 90°
- gamma (hip rotation): -60° to 60°

## robot_hat.Ultrasonic

```python
from robot_hat import Ultrasonic, Pin
sonar = Ultrasonic(Pin("D2"), Pin("D3"), timeout=0.02)
distance = sonar.read()    # Returns cm as float, may block
```

Trigger on D2, echo on D3. The `read()` can block if no echo received;
wrap with a signal timeout in production code.

## robot_hat.Music

```python
from robot_hat import Music
music = Music()

music.music_set_volume(30)           # 0-100
music.music_play(filename, loops=1, start=0.0, volume=None)
music.music_stop()
music.music_pause()
music.music_resume()

music.sound_play(filename, volume=None)            # Blocking SFX
music.sound_play_threading(filename, volume=None)  # Non-blocking SFX

music.play_tone_for(freq, duration)  # Play a tone at freq Hz for duration s
```

## robot_hat.Pin

```python
from robot_hat import Pin
pin = Pin("D2")  # Digital pin by name
```

Common pin names: `D2`, `D3`, etc. (check Robot HAT pinout).

## vilib.Vilib (Camera & Vision)

```python
from vilib import Vilib

# Start camera and display
Vilib.camera_start(vflip=False, hflip=False)
Vilib.display(local=True, web=True)
# Now visible at http://<pi-ip>:9000/mjpg

# Detection switches
Vilib.face_detect_switch(True|False)
Vilib.color_detect('close'|'red'|'orange'|'yellow'|'green'|'blue'|'purple')
Vilib.qrcode_detect_switch(True|False)
Vilib.gesture_detect_switch(True|False)
Vilib.traffic_sign_detect_switch(True|False)

# Results in detect_obj_parameter dict:
Vilib.detect_obj_parameter['color_x']     # Color block center X (0-320)
Vilib.detect_obj_parameter['color_y']     # Color block center Y (0-240)
Vilib.detect_obj_parameter['color_w']     # Color block width
Vilib.detect_obj_parameter['color_h']     # Color block height
Vilib.detect_obj_parameter['color_n']     # Number of color blocks

Vilib.detect_obj_parameter['human_x']     # Face center X
Vilib.detect_obj_parameter['human_y']     # Face center Y
Vilib.detect_obj_parameter['human_w']     # Face width
Vilib.detect_obj_parameter['human_h']     # Face height
Vilib.detect_obj_parameter['human_n']     # Number of faces

Vilib.detect_obj_parameter['gesture_x']   # Gesture X
Vilib.detect_obj_parameter['gesture_y']   # Gesture Y
Vilib.detect_obj_parameter['gesture_t']   # Type: paper|scissor|rock

Vilib.detect_obj_parameter['traffic_sign_x']  # Sign X
Vilib.detect_obj_parameter['traffic_sign_y']  # Sign Y
Vilib.detect_obj_parameter['traffic_sign_t']  # Type: stop|right|left|forward

Vilib.detect_obj_parameter['qr_data']     # QR decoded text
Vilib.detect_obj_parameter['qr_x']        # QR X
Vilib.detect_obj_parameter['qr_y']        # QR Y

# Capture photo
from time import strftime, localtime
name = f"photo_{strftime('%Y-%m-%d-%H-%M-%S', localtime())}"
Vilib.take_photo(name, "/home/ricardo/Pictures/")
# Saved as /home/ricardo/Pictures/photo_....jpg

# Cleanup
Vilib.camera_close()
```

## Servo Calibration

After assembly, run calibration before first use:

```bash
cd ~/picrawler/examples
sudo python3 0_calibration.py
# Follow the web UI at http://<pi-ip>:9000/
```

Servo offsets are saved to `~/.config/.picrawler.config`.

## Wiring Info

- Servos: I2C PCA9685 on Robot HAT, channels 0-11
- Ultrasonic: Trig=D2, Echo=D3
- Camera: PiCamera port
- I2S audio: Built into Robot HAT
- Power: 7-12V via Robot HAT barrel jack or 3-pin battery
