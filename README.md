# Picrawler

Picrawler Python library and examples for Raspberry Pi.

Quick Links:

- [Picrawler](#picrawler)
  - [Docs](#docs)
  - [Installation](#installation)
    - [install tool](#install-tool)
    - [robot-hat library](#robot-hat-library)
    - [vilib library](#vilib-library)
    - [picrawler library](#picrawler-library)
    - [Updating](#updating)
    - [OpenClaw skill](#openclaw-skill)
  - [Examples](#examples)
    - [Spanish voice](#spanish-voice)
    - [Petronilo voice assistant](#petronilo-voice-assistant)
    - [Twerk demo](#twerk-demo)
    - [Tricks](#tricks)
  - [About SunFounder](#about-sunfounder)
  - [Contact us](#contact-us)

----------------------------------------------

## Docs

- <https://docs.sunfounder.com/projects/pi-crawler/en/latest/>

----------------------------------------------

## Installation

This setup uses forks of the SunFounder libraries:

| Library | Repo | Branch | Changes from upstream |
|---------|------|--------|-----------------------|
| robot-hat | [rickhlx/robot-hat](https://github.com/rickhlx/robot-hat) | `2.5.x` | Runs on macOS / non-Pi machines with mocked hardware |
| picrawler | [rickhlx/picrawler](https://github.com/rickhlx/picrawler) | `main` | Spanish voices, Petronilo voice assistant, twerk demo |
| vilib | [sunfounder/vilib](https://github.com/sunfounder/vilib) | default | Upstream, not forked |

The upstream guide is still useful for background: <https://docs.sunfounder.com/projects/pi-crawler/en/latest/python/python_start/install_all_modules.html>

### install tool

```bash
sudo apt install git python3-pip python3-setuptools python3-smbus
```

### robot-hat library

Also installs `sunfounder-voice-assistant`, which the voice examples need.

```bash
cd ~/
git clone -b 2.5.x --depth=1 https://github.com/rickhlx/robot-hat.git
cd robot-hat
sudo python3 install.py
```

### vilib library

```bash
cd ~/
git clone --depth=1 https://github.com/sunfounder/vilib.git
cd vilib
sudo python3 install.py
```

### picrawler library

Clone to `~/picrawler`; `petronilo.service` expects the repo there.

```bash
cd ~/
git clone https://github.com/rickhlx/picrawler.git
sudo pip3 install ~/picrawler --break-system-packages
# used by twerk.py and the Petronilo assistant
sudo pip3 install numpy requests --break-system-packages
```

### Updating

```bash
cd ~/robot-hat && git pull && sudo python3 install.py
cd ~/picrawler && git pull
sudo pip3 uninstall picrawler --break-system-packages -y
sudo pip3 install ~/picrawler --break-system-packages
python3 -c "import robot_hat, picrawler; print(robot_hat.__version__, picrawler.__version__)"
sudo systemctl restart petronilo   # only if the Petronilo service is installed
```

If `~/robot-hat` or `~/picrawler` was cloned from SunFounder, point it at the fork before pulling. `reset --hard` discards uncommitted edits in that checkout (`examples/secret.py` is git-ignored and kept):

```bash
cd ~/robot-hat
git remote set-url origin https://github.com/rickhlx/robot-hat.git
git fetch origin 2.5.x && git checkout 2.5.x && git reset --hard origin/2.5.x

cd ~/picrawler
git remote set-url origin https://github.com/rickhlx/picrawler.git
git fetch origin main && git checkout main && git reset --hard origin/main
```

### OpenClaw skill

`picrawler-control/` is an OpenClaw skill that lets an agent drive the robot through natural-language commands. `picrawler-control/install.sh` installs the same libraries as above; see `picrawler-control/SKILL.md` for details.

----------------------------------------------

## Examples

Run examples with `sudo` (required for GPIO/servo access):

```bash
sudo python3 ~/picrawler/examples/1_move.py
```

| # | Example | Description |
|---|---------|-------------|
| 0 | `0_calibration.py` | Servo calibration helper (Space, then `y` to save; `make cali-pull` backs it up to `calibration/`) |
| 1 | `1_move.py` | Basic movement control |
| 2 | `2_keyboard_control.py` | W/A/S/D keyboard control |
| 3 | `3_sound_effect.py` | Sound effects and Spanish TTS |
| 4 | `4_avoid.py` | Obstacle avoidance with ultrasonic |
| 5 | `5_display.py` | Camera / computer vision display |
| 6 | `6_record_video.py` | Record video from camera |
| 7 | `7_bull_fight.py` | Bull fight interactive game |
| 8 | `8_treasure_hunt.py` | Treasure hunt game (calls out colours in Spanish) |
| 9 | `9_do_step.py` | Custom step coordinate control |
| 10 | `10_do_single_leg.py` | Adjust single leg posture |
| 11 | `11_record_new_step.py` | Record custom steps via keyboard |
| 12 | `12_twist.py` | Twist / body rotation to music |
| 13 | `13_emotional_robot.py` | Emotional expression robot |
| 14 | `14_preset_actions.py` | Pose demonstration (wave, look up/down, etc.) |
| 15 | `15_stt.py` | Speech-to-text demo |
| 16 | `16_tts.py` | Text-to-speech demo (Spanish Piper voice) |
| 17 | `17_online_llm_test.py` | Text chat with an OpenAI model (`gpt-5.6-luna`) |
| 18 | `18_voice_active_crawler_gpt.py` | Voice AI with OpenAI — the Spanish "Petronilo" assistant |
| 19 | `19_voice_active_crawler_doubao.py` | Voice AI with Doubao (Chinese, wake word 旺财) |
| 20 | `20_voice_active_crawler_ollama.py` | Voice AI with Ollama (local, Spanish) |
| 21 | `21_imu_check.py` | Print roll/pitch from an MPU6050 to check its mounting (`--axes` to remap) |
| 22 | `22_self_level.py` | Stand and hold the body level on a tilting surface (MPU6050) |
| 23 | `23_trot.py` | Keyboard-driven trot gait, optionally self-leveling (`--level`, `--max-dps`) |
| 24 | `24_tricks.py` | Crowd-pleaser tricks: bow, nod, shake head, shimmy, hula, bounce, spin, play dead, high five |
| | `twerk.py` | Reggaeton twerk dance to a synthesized dembow beat |
| | `servo_zeroing.py` | Servo zeroing utility |

Helper modules used by the examples (not run directly):

- `voice_active_crawler.py` — `VoiceActiveCrawler`, the voice assistant base class that maps LLM actions to robot moves.
- `petronilo_voice.py` — `PetroniloTTS` (OpenAI TTS with a persona, Piper fallback) and `HybridSTT` (offline Vosk wake word + OpenAI transcription).
- `memory.py` — `Memory`, long-term memory the assistant updates on its own after each conversation.
- `spanish_tts.py` — Mexican Spanish Piper model name and `EspeakES`, a Spanish Espeak voice.
- `petronilo.service` — systemd unit to run Petronilo on boot.

LLM examples read API keys from `examples/secret.py` (git-ignored), e.g.:

```python
OPENAI_API_KEY = "sk-..."
```

### Spanish voice

The TTS demos (`3_sound_effect.py`, `8_treasure_hunt.py`, `16_tts.py`) speak Mexican Spanish using the Piper model `es_MX-ald-medium`, which is downloaded to `~/.piper_models` on first use. Change `PIPER_MODEL` in `spanish_tts.py` to use another voice (e.g. an `es_ES-*` voice for Castilian Spanish).

### Petronilo voice assistant

`18_voice_active_crawler_gpt.py` runs "Petronilo", a Spanish-speaking, joke-cracking Mexican-uncle persona:

- **Wake word:** say "compa" (near-misses such as "compra" or "compadre" are accepted). After each answer he keeps listening for about 8 seconds, so follow-ups need no wake word; silence or a goodbye sends him back to waiting.
- **Speech:** OpenAI `gpt-4o-mini-tts` for his voice and `gpt-4o-transcribe` for what you say, each falling back to offline Piper / Vosk if the request fails. Speech starts after the first sentence while the rest of the answer is still streaming.
- **Actions:** the usual moves (forward, turn, sit, wave, look around...) plus `twerk` and `trot` (a fast run forward, triggered by "corre" / "trota") and the [tricks](#tricks) below. He nods and shakes his head along with what he says, bows for applause, and plays dead when you say "bang". Twerk, trot, spin and bounce are refused on a low battery.
- **Camera:** frames are sent to the model only for visual questions.
- **Memory:** when a conversation ends, a small model (`gpt-4.1-mini`) reads it and adds, corrects or forgets facts about the family, plus a one-line summary of the chat, in `petronilo_memory.json` (Pi-local, not tracked). Both are in his prompt from the next turn on; nobody has to say "acuérdate".

For a fully offline setup, switch to the Piper TTS / Vosk STT lines commented in the script, or use `20_voice_active_crawler_ollama.py`.

To run Petronilo on boot with auto-restart:

```bash
sudo cp -r ~/.piper_models ~/.vosk_models /root/   # the service runs as root
sudo cp ~/picrawler/examples/petronilo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now petronilo
journalctl -u petronilo -f                          # logs
```

The unit assumes the repo lives at `/home/ricardo/picrawler`; edit `WorkingDirectory` and `ExecStart` if yours differs.

### Twerk demo

`twerk.py` synthesizes a reggaeton dembow beat with numpy on first run (saved to `musics/reggaeton_dembow.wav`) and dances a 12-bar routine in time with it.

```bash
sudo python3 ~/picrawler/examples/twerk.py --bpm 100 --volume 40 --speed 70
```

Options: `--bpm` (default 95), `--volume` 0–100 (default 100), `--speed` servo speed 0–100 (default 90), `--regen` to re-synthesize the beat. Lower `--speed` and `--volume` if the Pi browns out — running all twelve servos fast with a loud amplifier draws a lot of current.

### Tricks

`picrawler/tricks.py` has party tricks built as body-frame keyframes: `bow`, `nod`, `shake head`, `shimmy`, `hula`, `bounce`, `spin`, `play dead` and `high five`. Each one stands up, performs, and ends in the stand pose.

```bash
sudo python3 ~/picrawler/examples/24_tricks.py                 # all of them
sudo python3 ~/picrawler/examples/24_tricks.py "play dead" bow # just these
```

From Python it is `Picrawler().trick("high five")`; from the OpenClaw skill, `pc.py trick "high five"`.

----------------------------------------------

## About SunFounder

SunFounder is a technology company focused on Raspberry Pi and Arduino open source community development. Committed to the promotion of open source culture, we strives to bring the fun of electronics making to people all around the world and enable everyone to be a maker. Our products include learning kits, development boards, robots, sensor modules and development tools. In addition to high quality products, SunFounder also offers video tutorials to help you make your own project. If you have interest in open source or making something cool, welcome to join us!

----------------------------------------------

## Contact us

website:
    www.sunfounder.com

E-mail:
    service@sunfounder.com, support@sunfounder.com
