# Deploying changes

You edit code on your computer. The Pi gets a copy by rsync. Nothing is ever
`git pull`ed on the robot — its checkout is a deployment target, not a clone
you work in.

## The loop

```bash
make sync-dry     # what would change
make sync         # push the working tree
make deploy       # push, then restart petronilo
make logs         # follow the service log
make deployed     # what the Pi is actually running
```

`make deployed` prints the commit, branch and time of the last sync, because
the Pi's own git history no longer tells you anything:

```
89db623-dirty main 2026-09-20T12:04:11Z
```

A `-dirty` suffix means you deployed uncommitted changes. Fine while you are
iterating on hardware, not fine to leave running — commit and redeploy when it
works.

The host is the `picrawler` SSH alias. Override it for a second robot:

```bash
make deploy PI_HOST=pi2.local
```

## What is never synced

`make sync` runs with `--delete`, so anything not in your working tree is
removed from the Pi — except the Pi-local state that is explicitly excluded:

- `examples/secret.py` — the API keys
- `examples/petronilo_memory/` — what he remembers about the family, his
  transcripts, his pending reminders
- `examples/petronilo_mcp.json` — MCP servers and their tokens
- generated media (`musics/reggaeton_dembow.wav`, `img_input.jpeg`)
- `DEPLOYED`, lgpio's notify pipes, `__pycache__`, build artifacts

If you add a new file that lives only on the robot, add it to `EXCLUDES` in the
Makefile *before* the next sync, or `--delete` will take it.

## The editable install

The Pi must have picrawler installed in editable mode, or `picrawler/` changes
sync across and are then ignored in favour of the copy in site-packages:

```bash
sudo pip3 uninstall picrawler --break-system-packages -y
sudo pip3 install -e ~/picrawler --break-system-packages --no-deps --no-build-isolation
```

One time, on each Pi. Symptom when it is missing: the examples pick up your
changes, Petronilo does not.

## Restarting

`make deploy` restarts the service for you. By hand on the Pi:

```bash
sudo systemctl restart petronilo
sudo systemctl stop petronilo        # frees the camera, mic and servos
journalctl -u petronilo -f
journalctl -u petronilo --since "10 min ago" | less
```

Skills and MCP servers are re-read when a conversation starts, so those need no
restart. Anything in Python does: the prompt, the action map, `SOUL.md`, the
tool definitions.

## Calibration

The servo offsets live on the Pi at `/root/.config/.picrawler.config` and a
copy lives in the repo so a reflash does not cost you an evening:

```bash
make cali-pull    # Pi -> calibration/picrawler.config, then commit it
make cali-push    # repo -> Pi, overwriting what is there
```

`cali-pull` checks the file actually contains offsets before overwriting the
repo copy, so a failed SSH will not silently blank it.

## Before you deploy

Run the tests if you touched the agent, memory, scheduler, control socket or
policy:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

They are stdlib `unittest` with no dependencies and run on your computer — the
agent brain is tested against a stub `claude_agent_sdk`, and `robot_hat` is
never imported. There is no linter or type checker.

Deploy from `main` with a clean tree unless you are iterating on hardware,
which is the one case where `-dirty` on the robot is the point.

## Working on a Mac without a robot

`robot_hat`'s fork mocks GPIO, I2C and audio on non-Pi hosts, so `import
picrawler` works for anything that does not need real servos:

```bash
pip3 install -e ~/src/robot-hat          # the 2.5.x fork
python3 -c "import picrawler; print(picrawler.__version__)"
```

Set `ROBOT_HAT_MOCK=1` to force the mock on a Pi. What you cannot test this way
is timing, current draw or anything to do with the body actually holding
itself up.
