# Picrawler docs

How-to guides for this fork of the SunFounder PiCrawler — the robot itself and
Petronilo, the Spanish-speaking assistant that lives on it.

Start wherever you are:

| Guide | Read it when you want to |
|-------|--------------------------|
| [Getting started](getting-started.md) | Go from a fresh Raspberry Pi to a robot that stands, walks and talks |
| [Talking to Petronilo](petronilo.md) | Live with him day to day: wake word, what he can do, reminders, Telegram |
| [Seeing with the camera](camera.md) | Photos, video, face and colour detection, finding things, his eyes |
| [Sensors](sensors.md) | Ultrasonic distance, battery, IMU — and how he reads them himself |
| [Deploying changes](deploying.md) | Edit code on your computer and get it onto the robot safely |
| [Teaching Petronilo new tricks](extending-petronilo.md) | Add an action, a tool, a skill, an MCP server or a command |
| [Writing moves](writing-moves.md) | Program the body directly: poses, gaits, tricks, self-leveling |
| [Making him feel faster](latency.md) | Where the seconds go, what was done, what is left |
| [Moving him to another network](wifi.md) | Take him to a different house without losing SSH |
| [Troubleshooting](troubleshooting.md) | Something is broken and you want the fix, not the theory |
| [Pi and HAT configuration](pi-config.md) | Know exactly how this Pi is set up, and what is still open |

The [top-level README](../README.md) has the install commands and the full list
of numbered examples. [`CLAUDE.md`](../CLAUDE.md) is the architecture reference
for anyone (or anything) editing the code.

## The 30-second version

The robot is a Raspberry Pi wearing a Robot HAT, twelve servos, an ultrasonic
sensor and a camera. `picrawler/` is the library: inverse kinematics, gaits,
tricks, IMU leveling. `examples/` is everything built on top, and the one that
matters most is `18_voice_active_crawler_gpt.py` — Petronilo, who runs as a
systemd service from boot and thinks with a Claude agent.

You edit code on your computer. `make deploy` rsyncs it to the Pi and restarts
him. Nothing is ever `git pull`ed on the robot.

Two constraints explain most of the design decisions you will meet:

- **One 3 A rail** feeds the Pi, the servos and the speaker amp, so moving and
  talking at once browns the Pi out. Hence the speed caps, the one-move-per-
  reply limit, and the low-battery refusals.
- **Every interesting answer is a network call**, so latency is about hiding
  round trips, not about the model. Hence the pre-warmed sessions, the
  pre-rendered openers and the frame that rides along with a visual question.
