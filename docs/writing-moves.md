# Writing moves

How to program the body directly — poses, gaits, tricks — without going
through the voice assistant.

## The two frames

Everything comes down to where you put four feet, and there are two ways to say
it.

**Leg-local** is what the servos take. Each foot is `[x, y, z]` in millimetres
relative to its own hip: x out to the side, y along the body away from centre,
z height (negative is down). A frame is four of those, in the order
`[right front, left front, left rear, right rear]`.

```python
from picrawler import Picrawler

crawler = Picrawler()
crawler.do_step([[45, 45, -50]] * 4, speed=50)   # the stand pose
```

`X_DEFAULT = 45`, `Y_DEFAULT = 45`, `Z_DEFAULT = -50` (standing),
`Z_UP = -30` (lifted), `LENGTH_SIDE = 77` (hips on the corners of a 77 mm
square).

**Body frame** is what you want for anything expressive. It follows REP-103: x
forward, y left, z up, with roll positive lifting the left side and pitch
positive dropping the nose. `body.to_step(points, roll, pitch)` converts back
to a `do_step` frame.

Use leg-local for gaits, body frame for poses. Mixing them is where the
confusing bugs live.

## Poses

`tricks.pose()` builds a frame by moving the *body* while the feet stay
planted, which is how every trick here is written:

```python
from picrawler import tricks

tricks.pose(x=-10, z=-5, pitch=12)     # lean back and dip the nose
tricks.pose(roll=8)                    # lift the left side
tricks.pose(yaw=10)                    # twist in place
```

Translations are millimetres, rotations degrees. Out-of-reach numbers are
clamped silently by the servo limits, so a pose that "does nothing" is usually
a pose that asked for too much.

## Writing a trick

A trick is a list of `Move(feet, speed, hold)` that starts and ends at
`gait.NEUTRAL`:

```python
def peek():
    return [
        Move(pose(z=-8, pitch=-10), speed=50, hold=0.4),   # crouch, nose up
        Move(pose(y=15, roll=6), speed=45, hold=0.6),      # lean left to look
        Move(pose(), speed=55),                            # back to neutral
    ]

TRICKS["peek"] = peek
```

`hold` is seconds to wait after the move lands — the difference between a
gesture and a twitch. Run it:

```bash
sudo python3 examples/24_tricks.py peek
```

`Picrawler.trick(name)` wraps the whole thing in `neutral_stance()`, which
steps from the stand pose into NEUTRAL and back, so a trick never has to worry
about where the robot was standing.

Start slow — `speed=45` — and raise it once the shape is right. Fast and wrong
is how servos strip.

## Fidgets

Fidgets are the opposite: small gestures that start and end in *whatever* pose
the robot is already in, so they can run while he sits and talks.

```python
def sway(feet):
    """Shift the weight to one side and back."""
    return _there_and_back(feet, pose(y=random.choice((-6, 6)), feet=feet), 0.5)

FIDGETS["sway"] = sway
```

The trick is `pose(..., feet=feet)`: the pose is built *from the frame the
robot is standing in*, not from neutral, which is what lets a fidget run while
he sits. `_there_and_back` then returns there. They all run at `SPEED = 30`.

Keep them under a second and under about 8 mm or 7° of travel — anything bigger
reads as a move rather than a tic, and costs battery while he is mid-sentence.
All twelve servos may move, but barely, so the draw stays well under a trick's
while the amplifier is busy.

## Walking

The built-in gaits are `MoveList` properties, used by name:

```python
crawler.do_action("forward", step=3, speed=70)
crawler.do_action("turn left", step=1, speed=70)
crawler.turn_angle(180, side="left", speed=60)   # a half turn, 30 deg a cycle
```

`turn_angle` repeats the turn gait because one cycle only swings the feet so
far. It is nominal, not measured: feet slip on hard floors and there is no
compass, so a 180 lands a little short.

For anything faster, use the trot. `gait.Trot` is stateful, so the command can
change every half cycle — which is what makes keyboard driving work:

```python
crawler.trot(half_cycles=8, stride=30, turn=0, speed=100, lift=15)
```

```python
from picrawler import gait, body

trot = gait.Trot(lift=15)
for _ in range(8):
    for frame in trot.half_cycle(stride=30, strafe=0, turn=5):
        crawler.do_step(body.to_step(frame), speed=100)
for frame in trot.settle():
    crawler.do_step(body.to_step(frame), speed=100)
```

Diagonal pairs swing together. `stride` and `strafe` are millimetres per half
cycle, `turn` is degrees.

## Staying level

With an MPU6050 fitted, `balance.Leveler` holds the body level on a tilting
surface:

```python
from picrawler import balance, body, imu

attitude = imu.Attitude(imu.MPU6050())
leveler = balance.Leveler(gain=3.0, limit=10.0)

roll, pitch = attitude.update()
r, p = leveler.update(roll, pitch, dt)
crawler.do_step(body.to_step(gait.NEUTRAL, roll=r, pitch=p), speed=60)
```

It is an integral controller with a disc clamp, and it is quasi-static: the
servos have no feedback, so it holds a level stance on a slope, it does not
catch the robot when someone pushes it. Standing corrects up to about 11°,
trotting with the default 15 mm lift about 6°, both limited by the shoulder
servo's −10° stop.

See [Sensors](sensors.md) for checking the IMU's mounting first — the axes
depend on how it is glued down, and `axes=("-y", "x", "z")` remaps them without
touching the maths.

## Speed, and why it is capped

`speed` is 0–100 and maps onto a servo rate. Two caps sit above it:

```python
Picrawler(max_dps=428)      # servo degrees/second (stock servos)
Picrawler(speed_limit=40)   # cap on every move's speed, whatever the caller asks
```

Petronilo sets `speed_limit` to 40 while he is talking and 70 when he is not,
because the servos and the speaker amp share one 3 A rail and doing both at
once browns the Pi out. If you are writing a standalone script you own the
whole rail — but twelve servos starting together is still the failure mode, so
raise speed before you raise the number of legs moving at once.

## Testing without a robot

`import picrawler` works on macOS with the robot-hat fork installed, which
mocks GPIO, I2C and audio. Frame maths, gait generation and trick shapes can
all be checked there:

```python
frames = tricks.TRICKS["bow"]()
print(len(frames), frames[0].speed)
```

What you cannot check is timing, current draw, or whether the body actually
holds itself up. For that there is the floor.
