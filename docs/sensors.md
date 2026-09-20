# Sensors

Besides the camera, the robot has three things it can feel: how far away the
nearest obstacle is, how much battery is left, and (if you fit one) which way
is down.

| Sensor | Hardware | Read it with | Agent tool |
|--------|----------|--------------|------------|
| Ultrasonic | HC-SR04 on `D2` (trigger) / `D3` (echo) | `seeker.Sonar()` | `sensors` |
| Battery | Robot HAT ADC | `VoiceActiveCrawler.battery_voltage()` | `sensors` |
| IMU | MPU6050 on I2C `0x68` | `imu.MPU6050` / `imu.Attitude` | — |

## Ultrasonic

The raw driver comes from `robot_hat` and is happy to hand you nonsense — a
single read returns `-1` or `-2` when the echo times out, which happens
constantly against soft or angled surfaces:

```python
from robot_hat import Pin, Ultrasonic

sonar = Ultrasonic(Pin("D2"), Pin("D3"))
sonar.read()        # cm, or -1 / -2 on timeout
```

Use `seeker.Sonar` instead unless you have a reason not to. It takes five
reads 30 ms apart, throws away the timeouts, and returns the median — or
`None` when nothing echoed back at all:

```python
from seeker import Sonar

distance = Sonar()()        # cm, or None
```

`None` means "nothing within range", not "zero". Treat it as open floor, which
is what `Seeker` does when it walks towards something.

Range is roughly 3 cm to 4 m, and it reads the *nearest* thing in a wide cone
in front, not what the camera is looking at. It cannot see a table edge, a
chair leg at ankle height, or anything the beam glances off at an angle. Plan
around that: the robot stops for walls and people, and falls down stairs.

### Is it a tool the agent can use?

Yes. The agent's `sensors` tool returns both readings in one call:

```json
{"battery_volts": 7.82, "distance_cm": 41.0}
```

There is no separate distance tool — battery and distance come together,
because the two questions he actually gets asked ("¿qué tan lejos estoy de la
pared?", "¿cómo andas de pila?") are cheap enough to answer at once. The tool
runs in the voice service (the root process that owns the hardware), not in
the agent's unprivileged user, and is defined in `robot_tools()` in
`examples/petronilo_agent.py` alongside `move`, `find` and `look`.

The sonar is also used without being asked: `find <object>` stops the robot
about 15 cm short of whatever it has walked up to, whichever comes first
between the sonar and the object filling the camera frame.

On the legacy (non-agent) path there is no equivalent — the `ACTIONS:` line
only dispatches movement, so `AGENT = False` means no sensor readings in
conversation.

### Obstacle avoidance without any model

`4_avoid.py` is the whole behaviour in one loop: read a filtered distance,
turn away if something is closer than the threshold, otherwise step forward,
and beep when it changes its mind.

```bash
sudo python3 ~/picrawler/examples/4_avoid.py
```

It reimplements the median filter locally with a hardware timeout, which is
worth reading if you are writing a loop that must never block on a dead
sensor.

## Battery

```python
vad.battery_voltage()       # volts, from the HAT's ADC
```

The pack is 2S li-ion: 8.4 V full, 7.4 V nominal, and the Pi has browned out
at 7.43 V under servo load. That is why the low-battery threshold is 7.3 V and
not the cell chemistry's floor — the resting voltage badly overstates what is
left once twelve servos pull at once.

Below `BATTERY_LOW_VOLTS` Petronilo complains in character (at most every ten
minutes) and refuses the moves that drive every servo at once: `twerk`, `trot`,
`spin`, `bounce`. The refusal happens before the model answers, so he can tell
you why instead of silently not moving.

`make status` prints the last reading along with his spend and pending jobs.

## IMU (optional)

Fit an MPU6050 on the HAT's I2C header and the robot can tell which way it is
tilted, which is what `balance.Leveler` uses to keep the body level on a slope.
Check the mounting first — the axes depend on how you glued it down:

```bash
sudo python3 ~/picrawler/examples/21_imu_check.py --axes x,y,z
sudo python3 ~/picrawler/examples/22_self_level.py
sudo python3 ~/picrawler/examples/23_trot.py --level
```

Roll positive lifts the left side, pitch positive drops the nose. If the signs
come out backwards, remap with `axes=("-y", "x", "z")` and similar rather than
patching the maths.

Leveling is quasi-static: the servos have no position feedback, so this holds
a level stance on a tilting surface, it does not catch the robot when it is
pushed. The correction is clamped at the shoulder servo's limit — about 11° of
tilt standing, about 6° while trotting with the default 15 mm foot lift.

`i2cdetect -y 1` shows `0x68` when the IMU is wired correctly. On the robot as
last audited it is not connected, so examples 21–23 will fail until you add
one — see [pi-config](pi-config.md).

## Adding a sensor of your own

The pattern that has worked twice here: write a small callable class that
returns a clean value or `None`, keep the filtering inside it, and pass it in
rather than importing it deep in the logic. `Sonar` is nine lines and
`Seeker` takes it as an argument, which is why the search code can be run with
no hardware attached at all.

To make a new sensor visible to Petronilo, add a reading to
`VoiceActiveCrawler.sensor_readings()` — the `sensors` tool serialises whatever
that dict holds, so nothing else needs to change. Give the key a name the model
can interpret without a schema (`distance_cm`, not `d`).
