# Getting started

From a Raspberry Pi with a fresh SD card to a robot that stands, walks, and
answers when you call it. Budget an hour, most of it waiting on installs.

## What you need

- A PiCrawler kit: a Raspberry Pi (4 or 5), a SunFounder Robot HAT, twelve
  servos, the camera, and the 2S battery pack.
- Raspberry Pi OS (Bookworm or newer), SSH enabled, on the network.
- An OpenAI API key, and an Anthropic API key if you want Petronilo's agent
  brain. Both are optional for the movement examples.

A Pi 5 draws close to 2 A on its own and the HAT's regulator supplies 3 A for
everything including twelve servos. Brownouts are the single most common
problem on this robot — see [Power](pi-config.md#power) before you blame your
code.

## 1. Install the libraries

Everything below runs on the Pi. This fork uses patched versions of two
SunFounder libraries; install them in this order.

```bash
sudo apt install git python3-pip python3-setuptools python3-smbus

cd ~/
git clone -b 2.5.x --depth=1 https://github.com/rickhlx/robot-hat.git
cd robot-hat && sudo python3 install.py      # also installs sunfounder-voice-assistant

cd ~/
git clone --depth=1 https://github.com/sunfounder/vilib.git
cd vilib && sudo python3 install.py           # camera and vision

cd ~/
git clone https://github.com/rickhlx/picrawler.git
sudo pip3 install ~/picrawler --break-system-packages
sudo pip3 install numpy requests --break-system-packages   # twerk + Petronilo
```

Clone `picrawler` to `~/picrawler` exactly. The systemd unit, the Makefile and
the agent setup script all assume that path.

Check it took:

```bash
python3 -c "import robot_hat, picrawler; print(robot_hat.__version__, picrawler.__version__)"
```

If you plan to edit the code (you do — see [Deploying](deploying.md)), switch
to an editable install once so synced changes take effect without reinstalling:

```bash
sudo pip3 uninstall picrawler --break-system-packages -y
sudo pip3 install -e ~/picrawler --break-system-packages --no-deps
```

## 2. Calibrate the servos

Assemble the legs with the servos at zero, then correct the rest in software.
Nothing else works properly until this is done — an uncalibrated robot leans,
drifts when it walks, and falls over during tricks.

```bash
sudo python3 ~/picrawler/examples/0_calibration.py
```

Pick a leg with the number keys, nudge the joint with the arrow keys until the
foot sits where the diagram says, then Space and `y` to save. Offsets land in
`/root/.config/.picrawler.config` (the examples run under `sudo`, so it is
root's home, not yours).

Back the file up into the repo as soon as you are happy with it, from your
computer:

```bash
make cali-pull     # copies the Pi's offsets into calibration/picrawler.config
git commit -m "chore(calibration): recalibrate servos" calibration/picrawler.config
```

`make cali-push` sends the repo copy back, which is how you recover after
reflashing the SD card.

## 3. Make it move

```bash
sudo python3 ~/picrawler/examples/1_move.py            # stand, sit, walk
sudo python3 ~/picrawler/examples/2_keyboard_control.py # W/A/S/D
sudo python3 ~/picrawler/examples/14_preset_actions.py  # wave, look around
sudo python3 ~/picrawler/examples/24_tricks.py bow      # one trick
```

Every example needs `sudo`: `robot_hat` talks to GPIO and I2C directly.

If the robot twitches but does not stand, the calibration did not save. If it
moves once and the Pi reboots, that is a brownout — lower the speed and check
the battery.

## 4. Give it a voice

Put your keys in `examples/secret.py` on the Pi (git-ignored, and
`chmod 600` it — the agent user must not read it):

```python
OPENAI_API_KEY = "sk-..."
ANTHROPIC_API_KEY = "sk-ant-..."        # only for the agent brain
TELEGRAM_BOT_TOKEN = "..."              # optional
TELEGRAM_CHAT_IDS = [123456789]         # optional
```

Then wake Petronilo up by hand before you make him a service:

```bash
sudo python3 ~/picrawler/examples/18_voice_active_crawler_gpt.py
```

Say **"compa"**, wait for "¿Qué pasó, mijo?", and ask him something. If he
answers, the microphone, the speaker, the network and your key are all fine.
[Talking to Petronilo](petronilo.md) covers what he can do from here.

The first run downloads the offline voice models (Piper for speech, Vosk for
the wake word) to `~/.piper_models` and `~/.vosk_models`.

## 5. Set up the agent brain (optional)

With `AGENT = True` — the default — Petronilo thinks with a Claude agent that
can run a few shell commands, read the web, use skills and MCP servers, and
drive his own body. That agent runs as its own unprivileged user, which the
setup script creates:

```bash
sudo bash ~/picrawler/examples/petronilo/setup_agent.sh
```

It makes the `petronilo` user, installs `claude-agent-sdk`, tightens the
permissions on your home directory and `secret.py`, and tells you what is
still missing. Set `AGENT = False` in the script if you would rather he stayed
on the OpenAI model.

## 6. Run him on boot

```bash
sudo cp -r ~/.piper_models ~/.vosk_models /root/     # the service runs as root
sudo cp ~/picrawler/examples/petronilo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now petronilo
journalctl -u petronilo -f
```

The unit hard-codes `/home/ricardo/picrawler`; edit `WorkingDirectory` and
`ExecStart` if your username differs. It restarts on *any* exit, not just
failures, because the voice loop swallows exceptions and exits cleanly — a
robot that gives up after five crashes just goes quiet and nobody notices.

## Where to go next

- Day-to-day use: [Talking to Petronilo](petronilo.md)
- Changing the code: [Deploying changes](deploying.md)
- Programming the body: [Writing moves](writing-moves.md)
- Something wrong: [Troubleshooting](troubleshooting.md)
