# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Picrawler is a Python library for controlling a 4-legged spider robot (SunFounder PiCrawler) on Raspberry Pi. The library handles inverse kinematics, gait generation, and servo control. Version 2.1.4.

## Build / install

Build uses `pyproject.toml` (setuptools, no `setup.py`). Install via pip:

```bash
sudo pip3 install ~/picrawler --break-system-packages
```

For development iteration, the Pi uses an editable install (one-time) so the checkout at `~/picrawler` is what gets imported:

```bash
sudo pip3 uninstall picrawler --break -y && sudo pip3 install -e . --break --no-deps --no-build-isolation
```

Then push the Mac working tree to it with `make sync` (`make sync-dry` to preview, `make deploy` to sync and restart the `petronilo` service, `make logs` to follow it; host is the `picrawler` SSH alias, override with `PI_HOST=`). It excludes Pi-local state (`secret.py`, `petronilo_memory/`, generated media, lgpio pipes) so `--delete` never removes it. rsync is the only way code reaches the Pi: never `git pull` there, its checkout is just the target of the sync. Each sync writes `~/picrawler/DEPLOYED` on the Pi (`git describe --dirty`, branch, UTC time); `make deployed` prints it. `make wifi SSID="..."` pre-seeds a NetworkManager profile (password read from a prompt, keyfile installed root-owned 600, `powersave=2`) so he joins a new network headless; `make wifi-list`/`wifi-status` inspect it. See `docs/wifi.md`. Deploy from `main` with a clean tree unless you're iterating on hardware.

Tests live in `tests/` (stdlib `unittest`, no dependencies: `python3 -m unittest discover -s tests -p 'test_*.py'`), covering the agent's tool gate, memory, scheduler, control socket, the camera sweep (`Seeker`), wake-word matching and the agent brain (against a stub `claude_agent_sdk`, which is not installed on the Mac), the parts that run without robot_hat; run them after touching those modules. No linter or type-checker. Dependencies: `robot_hat` (installed separately from the fork <https://github.com/rickhlx/robot-hat>, `2.5.x` branch; its `install.py` also pulls in `sunfounder-voice-assistant`), `readchar`. `twerk.py` and `petronilo_voice.py` also need `numpy` and `requests`; Petronilo's agent brain needs `claude-agent-sdk` (its wheel bundles the Claude Code CLI; `examples/petronilo/setup_agent.sh` installs it).

This repo is a fork of `sunfounder/picrawler` (remote `origin` = `rickhlx/picrawler`). The robot-hat fork mocks GPIO/I2C/audio on non-Pi hosts, so `import robot_hat` / `import picrawler` work on macOS for development (`ROBOT_HAT_MOCK=1` forces the mock on a Pi).

## Architecture

```
picrawler/
  __init__.py          # Exports Picrawler class + __version__
  picrawler.py         # Core library (~650 lines)
  body.py              # Leg-local <-> body-frame geometry, body roll/pitch
  gait.py              # Trot generator (diagonal pairs) + reposition helper
  imu.py               # MPU6050 driver + complementary-filter Attitude
  balance.py           # Leveler: integral roll/pitch body leveling
  tricks.py            # Crowd-pleaser tricks (bow, shimmy, play dead, ...) as body-frame keyframes
  fidgets.py           # Small idle gestures (tilt, glance, nod, lean, tap) from the current pose
  llm.py               # Re-exports LLM classes from robot_hat.llm
  voice_assistant.py   # Re-exports VoiceAssistant from robot_hat.voice_assistant
  stt.py               # Re-exports STT from robot_hat.stt
  tts.py               # Re-exports TTS from robot_hat.tts
  version.py           # Version string (2.1.4)
examples/              # Numbered demo scripts (0-20 match the online course; 21-23 IMU/trot; 24 tricks; 25 find)
  voice_active_crawler.py     # VoiceActiveCrawler class (base, not numbered)
  wake.py                     # Wake-word matching over a transcript (fuzzy, mid-sentence, question detection)
  petronilo_voice.py          # PetroniloTTS (OpenAI TTS + Piper fallback), HybridSTT, SpeechPipeline
  spanish_tts.py              # Mexican Spanish Piper model name + EspeakES
  twerk.py                    # Reggaeton beat synthesis + twerk routine (also used by the "twerk" action)
  seeker.py                   # Seeker: scan with the camera, walk up, stop on the ultrasonic; VisionLocator, Sonar
  stream.py                   # camera only, served on :9000 (vilib web view); --face/--color/--qr
  petronilo.service           # systemd unit running 18_voice_active_crawler_gpt.py on boot
  memory.py                   # Memory: facts + chat summaries learned after each conversation; add/search/forget
  scheduler.py                # Scheduler: reminders ("say") and agent tasks ("ask") in jobs.json, fired when idle
  control.py                  # ControlServer: local Unix socket (say, ask, stop, remind, jobs, status)
  petronilo_ctl.py            # CLI client for the control socket (make ask/say/stop/status/jobs)
  telegram_bridge.py          # TelegramBridge: text in (allowlisted chats) -> agent -> text out; mirrors what he says alone
  petronilo_agent.py          # AgentBrain: Claude agent (claude-agent-sdk) with shell, skills, MCP and robot tools
  agent_policy.py             # Allow/deny for every agent tool call: command allowlist, read/write roots
  petronilo/SOUL.md           # Petronilo's personality, voice, limits and story (OpenClaw-style SOUL.md)
  petronilo/setup_agent.sh    # One-time Pi setup for the agent brain: unprivileged user, workspace, SDK
  petronilo_mcp.json          # External MCP servers for the agent (Pi-local, git-ignored)
  petronilo_memory/           # Petronilo's learned memory, OpenClaw-style Markdown (Pi-local, git-ignored)
  secret.py                   # API keys (git-ignored)
picrawler-control/     # OpenClaw skill: SKILL.md, references/api.md, scripts/pc.py, install.sh
docs/                  # human-facing how-to guides, indexed in docs/README.md
  getting-started.md   # fresh Pi -> standing, walking, talking robot
  petronilo.md         # daily use: wake word, actions, memory, reminders, Telegram, models
  camera.md            # vilib detection, Seeker, his eyes
  sensors.md           # ultrasonic, battery, IMU, and the `sensors` tool
  deploying.md         # the Mac -> Pi rsync workflow
  extending-petronilo.md # actions, robot tools, skills, MCP servers, commands
  writing-moves.md     # frames, poses, tricks, fidgets, gaits, leveling
  latency.md           # where the seconds go, what was done, what is left
  wifi.md              # moving him to another network headless
  troubleshooting.md   # symptom -> fix
  pi-config.md         # device audit: hardware, firmware, power, services
```

**`picrawler/picrawler.py`** — The single-file core:

- **`Picrawler(Robot)`** — Main class, extends `robot_hat.Robot`. Drives 12 servos (3 per leg × 4 legs) via PWM pins defined in `PIN_LIST`.
  - `coord2polar(coord)` / `polar2coord(angles)` — Inverse and forward kinematics converting between Cartesian leg-tip coordinates (x,y,z) and servo angles (alpha/beta/gamma).
  - `do_step(_step, speed)` — Execute one gait frame: either a list of 4 coordinate-tuples, or a named key into `self.step_list`.
  - `do_action(motion_name, step, speed)` — Repeat a named MoveList action `step` times.
  - `set_angle(angles_list, speed)` — Low-level servo angle write with limit clamping.
  - `cali_helper_web(leg, pos, enter)` — Per-leg calibration adjustment, persists offsets to `~/.config/.picrawler.config`.

- **`Picrawler.MoveList(dict)`** — Inner class defining all gait patterns as `@property` methods. Each property returns a list of frames, where each frame is 4 `[x, y, z]` leg-tip coordinates. Key gaits: `stand`, `sit`, `forward`, `backward`, `turn_left`, `turn_right`, `wave`, `push_up`, `look_left/right/up/down`, `turn_left_angle`, `turn_right_angle`. Uses two decorators:
  - `@check_stand` — Auto-prepends `stand` frames if the robot isn't standing.
  - `@normal_action(mode)` — Swaps leg order based on `stand_position` toggle (0 or 1), alternating the supporting vs. lifting legs each cycle.

- Leg ordering in coordinate lists: `[leg0, leg1, leg2, leg3]` = right front, left front, left rear, right rear. Leg-local frame: x sideways out of the body, y along the body away from its centre, z height (negative down).

- `Picrawler(max_dps=...)` overrides robot_hat's servo speed cap (428 deg/s, stock servos) for faster replacement servos. `Picrawler(speed_limit=...)` caps the 0-100 `speed` of every move whatever the caller asks for; Petronilo uses 40 while he is talking (`MOVE_SPEED_LIMIT`) and 70 when he is not (`MOVE_SPEED_IDLE`, applied per action in `_apply_speed_limit`), since it is driving the servos and the speaker amp at once that browns the Pi out — a find sweep or a half turn in silence can be quicker.

**IMU, leveling and trot** (`body.py`, `imu.py`, `balance.py`, `gait.py`) work in a body frame (REP-103: x forward, y left, z up; roll + lifts the left side, pitch + drops the nose) and produce `do_step` frames via `body.to_step(points, roll, pitch)`. `imu.MPU6050` talks through `robot_hat.I2C` at 0x68; `axes=` remaps a rotated mounting. `balance.Leveler` is an integral controller with a disc clamp: standing stays inside the shoulder servo's -10 deg limit up to ~11 deg of correction, trotting with the default 15 mm lift up to ~6 deg. `gait.Trot` is stateful (`half_cycle(stride, strafe, turn)`, `settle()`), so commands can change every half cycle. The servos have no feedback, so this is quasi-static leveling, not dynamic balance.

**Tricks** (`tricks.py`): each trick returns a list of `Move(feet, speed, hold)` in the body frame, built with `pose(x, y, z, roll, pitch, yaw)` (body shifted/rotated with the feet planted) and ending in `gait.NEUTRAL`. `Picrawler.trick(name)` runs one inside `Picrawler.neutral_stance()`, which steps from the stand pose into NEUTRAL and back (trot uses it too). Add a trick by writing the function and registering it in `TRICKS`.

**Fidgets** (`fidgets.py`): small slow gestures that start and end in whatever pose the robot is in (usually sit), so no stand or neutral stance. `Picrawler.fidget(name=None)` runs one, random by default. `VoiceActiveCrawler(fidget_every=(min, max))` runs one every few seconds on the action thread while speech is playing and no action is running, skipped on a low battery; Petronilo uses `(3, 7)`. They are code-driven, not LLM actions, so the prompt's "move little" rule still holds.

## Key physical constants

Defined in `MoveList`: `LENGTH_SIDE = 77` (body width), `X_DEFAULT = 45`, `Y_DEFAULT = 45`, `Z_DEFAULT = -50` (standing height), `Z_UP = -30` (sitting/lifted height). All in mm.

## Voice assistant integration (new in 2.5)

`VoiceActiveCrawler` extends `robot_hat.voice_assistant.VoiceAssistant` to provide wake-word-driven AI conversation with action execution. It follows the same pattern as pidog's `VoiceActiveDog`.

### Lifecycle (inherited from VoiceAssistant)

Each conversation round: `before_listen` → wait for wake word → `on_wake` → record speech → `on_heard` → `before_think` → send to LLM → `parse_response` → `before_say` → TTS speaks → `after_say` → `on_finish_a_round`.

`parse_response(text)` splits the LLM response on `ACTIONS: ` delimiter. Left side is the spoken reply, right side is comma-separated action names dispatched to `Picrawler.do_action()`. Actions run on a background thread so they don't block TTS.

### Supported actions

`forward`, `backward`, `turn left`, `turn right`, `turn 90`, `turn 180`, `sit`, `stand`, `wave`, `push up`, `twerk`, `trot`, `look left`, `look right`, `look up`, `look down`, and the tricks `bow`, `nod`, `shake head`, `shimmy`, `hula`, `bounce`, `spin`, `play dead`, `high five` — mapped in `VoiceActiveCrawler.ACTION_MAP`. `find <object>` is parameterised: `normalize_action` turns it into `find:<object>` and `VoiceActiveCrawler.find` runs `seeker.Seeker` (turn in place until the vision model sees it, walk up, stop at 15 cm on the ultrasonic or when it fills the frame); the outcome is spoken once the round's actions finish, and needs `with_image` plus `locator=` (and `sonar=`). `where <object>` is the same sweep without the approach (`Seeker.scan`, `VoiceActiveCrawler.locate`): it stops facing the sighting and reports the bearing relative to where he was standing, for "where is the dog" rather than "go to the dog". `turn 90`/`turn 180` call `Picrawler.turn_angle`, which repeats the turn gait 30 deg at a time (nominal: the feet slip, and there is no compass). `twerk` runs the `twerk.py` routine and `trot` runs `Picrawler.trot()` forward; they, `spin` and `bounce` are refused on a low battery. `ACTION_ALIASES` maps Spanish action names the LLM may emit back to these keys; the prompt pins the `ACTIONS:` line to English.

### Petronilo (Spanish assistant, `18_voice_active_crawler_gpt.py`)

Who he is lives in `examples/petronilo/SOUL.md`, modelled on OpenClaw's SOUL.md: identity, core truths, voice, albures, limits, body (including why he moves little and slowly), what he can do and how he treats memory. The script reads it at start-up and places it inside `INSTRUCTIONS`, which keeps only the operating parts the code depends on: the English `ACTIONS:` rule, the action names and when to use them, `find <object>`, and the reply format. Personality changes go in SOUL.md; a new action goes in `INSTRUCTIONS` and `ACTION_MAP`. Restart after editing either.

Extra `VoiceActiveCrawler` options used here: `stt=` (HybridSTT: offline Vosk for wake word / end of speech, `gpt-4o-transcribe` for the text), `follow_up_seconds` (keep listening after an answer without the wake word), `end_phrases`, `stream_speech` (speak sentence by sentence while the LLM streams), `memory_dir` / `memory_llm` (when a conversation ends, `memory.Memory.learn` sends the transcript to `memory_llm`, which returns add/update/delete edits to the stored facts plus a summary; the system prompt, pinned against history trimming, is rebuilt with them every turn), `battery_low_volts` / `battery_warning`. Wake word is "compa" with accent-insensitive near-miss aliases (`wake.py`), matched wherever it falls in the sentence; when it came with a question ("compa, ¿qué hora es?") that utterance's audio is re-read by `gpt-4o-transcribe` and answered directly, skipping `answer_on_wake` and the second listen (`HybridSTT.last_pcm` / `wake_transcribe`; no audio or no network and he asks as before). Camera frames are sent only for visual questions.

His memory (`examples/petronilo_memory/`) is a Markdown workspace laid out like OpenClaw's, Pi-local and git-ignored unlike SOUL.md: `USER.md` (the family), `MEMORY.md` (plans, running jokes, requests) and `memory/YYYY-MM-DD.md` daily notes with one line per conversation; the prompt gets both files plus the two most recent daily notes. `transcripts/YYYY-MM-DD.md` keeps every conversation word for word (`Memory.log_conversation`, one `## HH:MM` block each, pruned after `transcript_days`, 90); it never goes in the prompt, only `search` (the `recall` tool) reads it, so "what did I tell you yesterday" finds the sentence and not just the daily note. `agent_session.json` holds the last agent session id for resuming (below). Facts are the `- ` bullets, so the files can be edited by hand with the service stopped. An old `petronilo_memory.json` is migrated on first start and renamed `.migrated`.

### Agent brain (`petronilo_agent.py`)

With `AGENT = True` (the default) Petronilo answers through `VoiceActiveCrawler(brain=AgentBrain(...))`, a Claude agent driven by `claude-agent-sdk`, instead of `self.llm` and the `ACTIONS:` line; the OpenAI LLM then only serves the base class, and `memory_llm`, TTS and STT stay on OpenAI. The prompt is `AGENT_INSTRUCTIONS` (SOUL.md plus how to use the tools). One conversation is one agent session, and a conversation that starts within `AGENT_RESUME_MINUTES` (30) of the last one ending resumes it (`resume=`, id kept in `petronilo_memory/agent_session.json` across restarts), so he still has the last exchange word for word; the system prompt is sent as `{"type": "custom", "snapshot": False}` so a resumed session also gets the memory learned since. Past the window he starts fresh with what memory wrote down. `_connect` re-checks the window at the wake word, since the next session is prewarmed right after a conversation ends, and a resume whose transcript is gone is retried once without it. The date, time, last battery reading and last sonar distance (read in the background at the wake word, so a distance question costs no `sensors` round trip) come with every message through a `UserPromptSubmit` hook (`VoiceActiveCrawler.turn_context`), not the system prompt, which keeps the prompt byte-stable for the cache; the legacy LLM path keeps its `## Ahora` section.

Two privilege levels. The robot tools (`move`, `find`, `where`, `look`, `sensors`, `remember`/`recall`/`forget`, `remind`/`reminders`/`cancel_reminder`) are an in-process MCP server that runs in the root voice service; `move` queues onto the action thread, so the body moves while he talks, capped by `max_actions`, and refuses the heavy moves (`HEAVY_ACTIONS`) up front on a low battery so he can say so. `find` and `where` also run on the action thread (`seek` and `locate` route themselves there with `run_on_action_thread`), otherwise the fidgets would drive the servos while he walks; both call `_announce_first()` so the sentence that announced the search finishes playing before the body turns (the first sentence is synthesized over the network, so without it the move lands first). The Claude Code CLI runs as `AGENT_USER` (`petronilo`) with cwd `AGENT_WORKSPACE`; Bash, skills (`~petronilo/.claude/skills/`) and external MCP servers (`examples/petronilo_mcp.json`, Claude Code's `mcpServers` format) run as that user. `setting_sources=["user"]` so nothing is loaded from the writable workspace, and `DISALLOWED_TOOLS` (subagents, AskUserQuestion, ...) never reach the model. Every other tool call passes a `PreToolUse` hook backed by `agent_policy.verdict`, with `permission_mode="dontAsk"` behind it: `can_use_tool` is not enough, because allow rules in settings files approve tools before it is consulted. The policy allows Bash only when every pipeline segment starts with a name in `AGENT_COMMANDS` and there are no redirects, substitutions or `$` variables (the CLI's environment holds the API key), refuses the subcommands and flags in `DENIED_SUBCOMMANDS`/`DENIED_FLAGS` (`gh alias`/`extension`/`config` run commands; `curl -o`/`-d @file` and `jq -f`/`--rawfile` write or read files), keeps Read/Glob/Grep inside the workspace and skills, keeps writes inside the workspace but out of its `.claude/`, `.mcp.json` and `CLAUDE.md`, allows every tool of a configured MCP server, and denies anything else. Never add a command that runs other commands (`sh`, `python3`, `xargs`, `env`, `sudo`) or reads arbitrary files (`cat`, `grep`); `curl` is out too, WebFetch covers it. Setup: `sudo bash ~/picrawler/examples/petronilo/setup_agent.sh` on the Pi, then `ANTHROPIC_API_KEY` in `secret.py`.

Failure and cost. `think()` never raises: if the agent fails before he has said anything, that turn is answered by the OpenAI LLM instead; if it fails mid-sentence he says `BRAIN_ERROR_PHRASE`. (The base `VoiceAssistant.run()` swallows exceptions and exits 0, which is why `petronilo.service` uses `Restart=always`.) Two spend caps: the SDK's `max_budget_usd` per conversation (`AGENT_BUDGET_USD`) and `daily_budget_usd` (`AGENT_DAILY_BUDGET_USD`), past which `AgentBrain.ask` raises `BudgetExceeded` and he says `BUDGET_PHRASE`. Each conversation logs its cost, turns and duration to the journal; `ResultMessage.total_cost_usd` is the connection's running total (streaming input mode), so `_add_cost` adds only the increase per turn. `fallback_model` (`AGENT_FALLBACK_MODEL`, `claude-sonnet-5`) keeps him in the agent with his tools when `AGENT_MODEL` (`claude-fable-5-1`, effort `low`) is overloaded, before the OpenAI fallback. `MCP_TOOL_TIMEOUT` is raised so a long `find` is not abandoned by the CLI; the CLI's stderr goes to the journal as `(agente cli: ...)` and a `PreCompact` hook logs when a long session compacts.

Memory and reminders are tools too. `remember`/`recall`/`forget` call `Memory.add_fact`/`search`/`remove_fact` in-process (the files stay root-owned; the agent user never reads them), so he can save or look something up mid-conversation instead of waiting for the end-of-conversation extraction, which still runs. `remind`/`reminders`/`cancel_reminder` drive `scheduler.Scheduler` (`petronilo_memory/jobs.json`): a `say` job is spoken verbatim when due, an `ask` job is a prompt run through `run_task`. The per-turn context from the `UserPromptSubmit` hook gives him the local date and time so he can compute ISO times.

Acting on his own. `VoiceActiveCrawler.run_task(prompt, speak=True)` is one agent turn outside a conversation: it waits until he is idle (`_idle`, cleared at the wake word, set when the conversation's memory pass ends), takes `_task_lock` (the wake word waits on it too), streams to speech, then closes the session. `say(text)` speaks a line under the same rules; `stop_speaking()` cancels the current `SpeechPipeline` (the sentence already playing finishes), drains the action queue and sits. The scheduler tick thread fires due jobs through these, so a reminder due mid-conversation is spoken when it ends. Whatever he says on his own also goes to `notify` (the Telegram bridge's `send`) when configured. Sessions are now pre-warmed: `_end_conversation` closes the session, learns memory, rebuilds the prompt and opens the next session, so the CLI start-up is off the next wake word's path and the new memory is already in it.

Control channels. `control.ControlServer` listens on `/run/petronilo.sock` (mode 600, so `sudo`): one JSON request per connection, `say`, `ask`, `stop`, `remind`, `jobs`, `cancel`, `status`. `petronilo_ctl.py` is the client and the Makefile wraps it (`make ask MSG="..."`, `make say`, `make stop`, `make status`, `make jobs`); it is also the headless way to test him without the mic. `telegram_bridge.TelegramBridge` long-polls with the standard library only; set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_IDS` (list of ints) in `secret.py`. Unknown chats get their chat id back once so you can allowlist them; allowed chats get written answers (`run_task(..., speak=False)`), plus `/stop`, `/jobs`, `/status`. Nothing here listens while he speaks: barge-in by voice is still open.

Latency is the thing to watch. The session opens at the wake word (`brain.start`) so the CLI's start-up overlaps the listening, MCP tools load up front (`ENABLE_TOOL_SEARCH=false`, no ToolSearch turn), the prompt has him speak a sentence before any tool call, and a visual question (`_wants_image`) carries the camera frame in the user message (`brain.ask(..., image_path=)`, an image block ahead of the text) so it needs no `look` round trip. `petronilo_voice.Fillers` renders a handful of short openers once into `~/.petronilo_fillers`, and `SpeechPipeline` plays one only if the first real sentence is not ready within 0.7 s (through the same play worker, so it can never overlap the answer); the transcription and vision calls reuse a `requests.Session`. With those, on the Mac: first words about 2 s after the question, full answer with one tool call about 5 s. `docs/latency.md` tracks what is left.

Adding to what he can use, all on the Pi. Skills and MCP servers are read when a conversation starts, so they need no restart; a command does.

- **Skill**: copy the folder holding `SKILL.md` into `/home/petronilo/.claude/skills/` and `sudo chown -R petronilo:` it. He can read a skill's files but runs only allowlisted commands, so skills that are instructions work; skills that ship scripts don't.
- **MCP server**: add it to `examples/petronilo_mcp.json` (`{"mcpServers": {"name": {"command": ..., "args": [...], "env": {...}}}}`, Claude Code's format) and `chmod 600` it, since it holds tokens. It runs as `petronilo`, and every tool it has is allowed. Install its runtime first: the Pi has no `node`/`npx` or `uv`/`uvx`.
- **CLI tool**: install it (`sudo apt install gh`), log it in as the agent's user (`sudo -u petronilo -H gh auth login`), make sure its name is in `AGENT_COMMANDS`, then `make deploy`. Never allowlist a command that runs others (`sh`, `python3`, `npx`, `xargs`, `env`, `sudo`) or reads arbitrary files (`cat`, `grep`): either one gets around the policy.

### LLM backends

Re-exported from `robot_hat.llm`: `OpenAI`, `Ollama`, `Doubao`, `DeepSeek`, `Gemini`, `Grok`, `Qwen`. Each takes provider-specific kwargs (api_key, model, ip for Ollama, etc.).

## Running examples

All examples must run on the Raspberry Pi with `sudo` (required by `robot_hat` for GPIO/servo access). Examples are numbered to match the online course at <https://docs.sunfounder.com/projects/pi-crawler/en/latest/python/play_with_python.html>.

```bash
# Core course examples (0-13)
sudo python3 examples/0_calibration.py       # Servo calibration
sudo python3 examples/1_move.py              # Basic movement
sudo python3 examples/2_keyboard_control.py  # W/A/S/D control
sudo python3 examples/3_sound_effect.py      # Sound effects
sudo python3 examples/4_avoid.py             # Obstacle avoidance
sudo python3 examples/5_display.py           # Camera display
sudo python3 examples/7_bull_fight.py        # Bull fight game
sudo python3 examples/8_treasure_hunt.py     # Treasure hunt (Spanish colour names)
sudo python3 examples/9_do_step.py           # Custom step control
sudo python3 examples/12_twist.py            # Twist to music

# Extended examples (14)
sudo python3 examples/14_preset_actions.py   # Pose demonstration

# STT/TTS demos (15-16), TTS in Spanish
sudo python3 examples/15_stt.py              # Speech-to-text
sudo python3 examples/16_tts.py              # Text-to-speech

# LLM / Voice AI (17-20)
sudo python3 examples/17_online_llm_test.py               # Text chat, OpenAI gpt-5.6-luna
sudo python3 examples/18_voice_active_crawler_gpt.py      # Petronilo, Spanish, OpenAI
sudo python3 examples/19_voice_active_crawler_doubao.py   # Doubao (Chinese)
sudo python3 examples/20_voice_active_crawler_ollama.py   # Local Ollama, Spanish

# IMU / leveling / trot (21-23); need an MPU6050 on the HAT I2C header (23 only with --level)
sudo python3 examples/21_imu_check.py --axes x,y,z       # Verify IMU signs
sudo python3 examples/22_self_level.py                    # Self-leveling stand
sudo python3 examples/23_trot.py --level                  # Keyboard trot

# Tricks (24)
sudo python3 examples/24_tricks.py "play dead" bow        # Named tricks; no args runs all of them

# Find an object (25); stop petronilo.service first, it holds the camera
sudo python3 examples/25_find.py "red cup"

# Not numbered
sudo python3 examples/twerk.py --bpm 95 --volume 40 --speed 70   # Reggaeton twerk
```

Configure API keys in `examples/secret.py` before running LLM-based examples.

## Calibration data

Servo offset calibration is stored at `~/.config/.picrawler.config`. The file is read/written by `robot_hat.Robot` via the `db` parameter passed to `super().__init__()`. The examples run under `sudo`, so on the Pi that is `/root/.config/.picrawler.config`.

A copy lives in the repo at `calibration/picrawler.config` so a reinstall keeps it. After recalibrating (Space, then `y` in `0_calibration.py`), run `make cali-pull` and commit the file. `picrawler-control/install.sh` restores it when the Pi has no offsets yet; `make cali-push` overwrites the Pi's offsets with the repo copy.

## Device configuration

`docs/` holds the human-facing how-to guides, indexed in `docs/README.md`: getting started, daily use, camera, sensors, deploying, extending the agent, writing moves, latency, Wi-Fi and troubleshooting. Keep them in step when behaviour changes — they are what a person reads, while this file is what an agent reads.

`docs/pi-config.md` records the Pi's hardware, firmware, boot config, audio routing, installed packages and services, with open findings from the last audit.
