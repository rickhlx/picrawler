# Troubleshooting

Symptoms first. Most of what goes wrong on this robot is power, and the second
most is the camera being held by something else.

## The Pi goes dead and the LED is red

A brownout. The Robot HAT's 5 V regulator supplies the Pi, twelve servos and
the speaker amp from one 3 A budget, and a Pi 5 alone can draw close to 2 A.
When several servos start together the rail sags and the PMIC powers the Pi
off; with `POWER_OFF_ON_HALT=0` it then sits in standby until you press the
button or cycle power.

```bash
vcgencmd get_throttled        # 0x0 is clean; 0x50000 means it happened
dmesg | grep -i voltage
cat /proc/device-tree/chosen/power/power_reset    # 0x2 = PMIC brownout
```

What helps, in order:

1. Charge the pack. Resting voltage lies: the Pi has browned out at 7.43 V.
2. Lower the speed of whatever you are running (`--speed 60`, or
   `MOVE_SPEED_LIMIT`/`MOVE_SPEED_IDLE` for Petronilo).
3. Lower the volume. The amplifier and the servos compete for the same rail,
   which is why he moves at a lower speed cap while talking than in silence.
4. Do not run `twerk`, `trot`, `spin` or `bounce` on a half-empty pack. He
   refuses them himself below 7.3 V.

Hardware fixes are in [pi-config](pi-config.md#power).

## He does not wake up

```bash
journalctl -u petronilo -f
arecord -l                     # is there a capture device at all?
arecord -d 3 /tmp/t.wav && aplay /tmp/t.wav
```

The wake word is offline (Vosk), so if he never answers "compa", it is the
microphone or the service, not the network. If the log shows
`No microphone detected!` the USB mic is unplugged or the I2S mic is not
enabled in `/boot/firmware/config.txt`.

He answers to "compra" and "compadre" on purpose — near misses are accepted,
because the small Vosk models garble short words.

If he wakes on "compa, ¿qué hora es?" but still asks what you wanted, the
cloud transcription of that sentence did not come back in time (six seconds);
the wake word itself is fine, the network is not.

## He wakes, then says nothing

Network or key. Everything past the wake word is a cloud call.

```bash
journalctl -u petronilo -n 50
ping -c1 api.openai.com
ssh picrawler "grep -c API_KEY ~/picrawler/examples/secret.py"
```

If he says **"se me fue la señal, mijo"**, the agent failed after he had
started talking — the real error is in the journal, often a timeout or an
overloaded model. If he says **"ya gasté mi domingo"**, the daily budget is
spent; it rolls over at midnight, and `make status` confirms.

## He answers but never moves

In order of likelihood:

1. He decided not to. He is told to move little: one action per reply, and
   usually none. This is by design, not a fault.
2. Low battery. Heavy moves are refused below 7.3 V and he says so.
3. Servos not calibrated, so "stand" puts him somewhere odd.
4. The action failed. The journal prints `(acción 'x' falló: ...)`.

## He moves before he says what he is doing

Fixed, but worth knowing the shape of it: the first sentence is synthesized
over the network while the tool call starts immediately, so the body used to
turn before "déjame echar un ojo" was audible. Tools that move now wait for the
announcing sentence to finish playing (`_announce_first`). If you add a tool
that moves, call it — see [extending](extending-petronilo.md#a-tool-his-senses).

## The camera fails or is black

Only one process can hold the camera. The service takes it at boot, so every
camera example fails until you stop him:

```bash
sudo systemctl stop petronilo
sudo python3 ~/picrawler/examples/25_find.py "red cup"
sudo systemctl start petronilo
```

If nothing can open it, check the ribbon cable seating and `libcamera-hello
--list-cameras`.

## Servos twitch, buzz or fight

- **Buzzing while still**: normal for these servos under load, but constant
  buzzing in the stand pose means the pose is fighting a limit. Recalibrate.
- **One leg out of place**: that leg's offsets are wrong. Run
  `0_calibration.py`, fix it, Space then `y`, and `make cali-pull` to save it.
- **Everything wrong after a reinstall**: the offsets live in root's home and
  were lost. `make cali-push` restores the repo copy.
- **Out of controllable range** printed: a frame asked for a foot position the
  legs cannot reach. The move is clamped, so the robot does something subtly
  wrong rather than failing loudly.

## Changes do not take effect

```bash
make deployed        # is the Pi running what you think?
```

- Library changes ignored → the editable install is missing. See
  [Deploying](deploying.md#the-editable-install).
- Prompt or action changes ignored → the service was not restarted.
  `make deploy` does both.
- A file you added on the Pi disappeared → `make sync` runs with `--delete`.
  Add it to `EXCLUDES` in the Makefile.

Skills and MCP servers are re-read at the start of every conversation and need
no restart.

## He cannot be reached at all

`make deployed` hangs, SSH times out. Usually the network changed or his
address moved: see [Moving him to another network](wifi.md). If he is on a
guest network, client isolation will keep him unreachable even though he has
internet.

## The agent refuses something

```
Refused: at most 1 move(s) per reply, to spare the battery.
```

That is `max_actions`. Other refusals come from `agent_policy.verdict`: a
command not in `AGENT_COMMANDS`, a pipeline with a redirect or a `$`, a read
outside the workspace. The journal logs the verdict. Do not work around a
refusal by allowlisting a shell — read
[the rules](extending-petronilo.md#a-command) first.

## Tests fail on your machine

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

They need no dependencies and never import `robot_hat`. If a test fails with
`ModuleNotFoundError`, something imported a hardware or network module at
module scope that should be imported lazily inside the function that uses it —
`Sonar` and `VisionLocator` both do this deliberately.

## Getting more detail

```bash
journalctl -u petronilo -f                     # live
journalctl -u petronilo --since "1 hour ago"   # after the fact
journalctl -u petronilo | grep "agente cli"    # the Claude CLI's own stderr
make status                                     # battery, idle, spend, jobs
```

Then, if nothing else: `sudo systemctl restart petronilo`. The unit restarts on
any exit, including clean ones, because the voice loop swallows exceptions and
exits 0 — so if he is truly wedged, the process is usually alive and waiting on
something, not dead.
