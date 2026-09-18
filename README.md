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
  - [Examples](#examples)
    - [Spanish voice](#spanish-voice)
    - [Petronilo voice assistant](#petronilo-voice-assistant)
    - [Twerk demo](#twerk-demo)
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
```

----------------------------------------------

## Examples

Run examples with `sudo` (required for GPIO/servo access):

```bash
sudo python3 ~/picrawler/examples/1_move.py
```

| # | Example | Description |
|---|---------|-------------|
| 0 | `0_calibration.py` | Servo calibration helper |
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
| 14 | `14_preset_actions.py` | Pose demonstration (wave, dance, look up/down, etc.) |
| 15 | `15_stt.py` | Speech-to-text demo |
| 16 | `16_tts.py` | Text-to-speech demo (Spanish Piper voice) |
| 17 | `17_online_llm_test.py` | Text chat with an OpenAI model (`gpt-5.6-luna`) |
| 18 | `18_voice_active_crawler_gpt.py` | Voice AI with OpenAI — the Spanish "Petronilo" assistant |
| 19 | `19_voice_active_crawler_doubao.py` | Voice AI with Doubao (Chinese, wake word 旺财) |
| 20 | `20_voice_active_crawler_ollama.py` | Voice AI with Ollama (local, Spanish) |
| | `twerk.py` | Reggaeton twerk dance to a synthesized dembow beat |
| | `servo_zeroing.py` | Servo zeroing utility |

Helper modules used by the examples (not run directly):

- `voice_active_crawler.py` — `VoiceActiveCrawler`, the voice assistant base class that maps LLM actions to robot moves.
- `petronilo_voice.py` — `PetroniloTTS` (OpenAI TTS with a persona, Piper fallback) and `HybridSTT` (offline Vosk wake word + OpenAI transcription).
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
- **Actions:** the usual moves (forward, turn, sit, wave, dance, look around...) plus `twerk`, which is refused on a low battery.
- **Camera:** frames are sent to the model only for visual questions.
- **Memory:** say "acuérdate que ..." and the fact is saved to `petronilo_memory.json` and loaded into the prompt on the next start.

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

----------------------------------------------

## About SunFounder

SunFounder is a technology company focused on Raspberry Pi and Arduino open source community development. Committed to the promotion of open source culture, we strives to bring the fun of electronics making to people all around the world and enable everyone to be a maker. Our products include learning kits, development boards, robots, sensor modules and development tools. In addition to high quality products, SunFounder also offers video tutorials to help you make your own project. If you have interest in open source or making something cool, welcome to join us!

----------------------------------------------

## Contact us

website:
    www.sunfounder.com

E-mail:
    service@sunfounder.com, support@sunfounder.com
