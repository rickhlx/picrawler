# Talking to Petronilo

Petronilo is the robot's personality: a Spanish-speaking tío who lives on the
Pi, runs from boot, and answers when you call him. This is the guide for using
him, not for changing him — that is
[Teaching Petronilo new tricks](extending-petronilo.md).

## The basics

Say **"compa"**. He answers "¿Qué pasó, mijo?" and listens. Near misses like
"compra" and "compadre" count, because Vosk is doing the wake-word listening
offline and it is not fussy.

After he answers he keeps listening for about eight seconds, so follow-ups need
no wake word. Say "adiós", "ya estuvo", "nos vemos" or just stay quiet and the
conversation ends.

He always replies in Spanish, whatever you speak to him in.

## What he can do

**Move.** Walk, turn, sit, stand, wave, push-ups, look around, plus the party
tricks: bow, nod, shake his head, shimmy, hula, bounce, spin, play dead, high
five. Ask in Spanish — "échate", "salúdame", "hazte el muerto", "chócalas".

"Date la vuelta" or "voltéate" turns him a half circle in place, "gira noventa
grados" a quarter. He turns in 30° steps, so a 180 takes a few seconds and
lands a little short — the feet slip and there is no compass to correct with.
That is a different thing from "da una vuelta", which is the `spin` party
trick.

He moves deliberately little while talking: one action per reply at most, at
40 % servo speed. That is not shyness, it is power — moving and talking at once
browns the Pi out. He does make small idle gestures on his own every few
seconds while he speaks, so he is not frozen.

**Dance and run.** "Perrea" plays a synthesized reggaeton beat and twerks to
it. "Corre" trots forward — much faster than walking. Both, plus spin and
bounce, are refused when the battery is low.

**Look.** Ask "¿qué ves?", "¿quién está aquí?", "¿de qué color es esto?" and a
camera frame goes with the question. See [the camera guide](camera.md).

**Find things.** "Búscame las llaves" — he turns in place looking through the
camera, walks up to what he finds, and stops before hitting it. He says
something short first, because he cannot talk while searching, and reports back
when he is done.

**Say where something is.** "¿Dónde está el perro?" is the same sweep without
the walking: he turns until he sees it, stops facing it, and tells you which
way it is relative to how he was standing — "está a tu izquierda, junto al
sillón". Use this one indoors, where you want to know, not to have a robot walk
across the room. Note that he ends up facing the dog, not you.

**Remember.** He keeps notes about the family on his own: after each
conversation a small model picks out what is worth keeping and writes it down.
You can also tell him directly — "acuérdate de que a Sofi no le gusta el
cilantro" — and he saves it mid-conversation. "¿Te acuerdas de…?" searches his
notes *and* the word-for-word transcripts of past conversations, so "¿qué te
dije ayer?" finds the actual sentence.

Nothing about memory requires special phrasing. Ask him to forget something and
he forgets it.

**Use the computer.** With the agent brain on, he can search the web, read
pages, run a handful of safe shell commands, use skills you install, and reach
any MCP server you configure. He is told to say something short before anything
slow, so a pause is announced rather than silent.

**Set reminders.** See below.

## Reminders and tasks

"Recuérdame sacar la carne a las ocho" schedules a reminder he speaks aloud
when the time comes. There are two kinds:

- **say** — he repeats the line in his own voice when it is due.
- **ask** — he *does* something then, like "revisa el clima y dime si va a
  llover". This runs a full agent turn, so it can use the web, the camera or
  anything else he has.

Reminders can repeat daily or weekly. "¿Qué pendientes tengo?" lists them,
"cancela el recordatorio de las ocho" removes one.

A reminder due mid-conversation waits until the conversation ends. He never
interrupts.

Everything is in `examples/petronilo_memory/jobs.json` on the Pi, so reminders
survive restarts.

## Talking to him without the microphone

Every one of these runs from your computer through the Makefile, over SSH:

```bash
make ask MSG="qué hora es"          # ask; he answers out loud on the Pi
make say MSG="ya llegó la pizza"    # make him say a line verbatim
make stop                            # cut whatever he is saying and doing
make status                          # battery, idle, spend today, pending jobs
make jobs                            # list reminders and tasks
```

This is the headless way to test him when you are not in the room, and the way
to script him: `make say` is how you make the robot announce something from a
cron job or a webhook.

On the Pi itself the client is `examples/petronilo_ctl.py`, which does a little
more than the Makefile exposes:

```bash
sudo python3 ~/picrawler/examples/petronilo_ctl.py remind +20m "saca la carne"
sudo python3 ~/picrawler/examples/petronilo_ctl.py remind 08:00 "buenos días" --repeat daily
sudo python3 ~/picrawler/examples/petronilo_ctl.py ask "qué hora es" --quiet
sudo python3 ~/picrawler/examples/petronilo_ctl.py cancel 3f9a2c
```

`WHEN` takes ISO-8601, `HH:MM` (today, or tomorrow if that time has passed) or
`+20m` / `+2h` / `+1d`. It needs `sudo`: the control socket is `0600` and owned
by the service.

## Telegram

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_IDS` in `examples/secret.py` and
he answers text messages too — in writing, without moving or taking photos,
with the same humour.

Message the bot from a chat that isn't on the list and he replies once with
that chat's id, so you can add it. `/stop`, `/jobs` and `/status` work as
commands.

Anything he says on his own — a reminder firing, a scheduled task finishing —
is mirrored to the allowed chats, which is how you find out the robot said
something to an empty room.

## Battery

He watches his own pack and complains when it drops below 7.3 V, at most every
ten minutes, and refuses the heavy moves. Believe him: the resting voltage
looks healthier than the pack really is under load, and a brownout takes the
whole Pi down, not just the servos.

`make status` gives you the number.

## When something is off

| It does this | Look at |
|--------------|---------|
| Doesn't wake up | Microphone, and `journalctl -u petronilo -f` |
| Wakes but never answers | Network, `OPENAI_API_KEY`, then the log |
| Says "se me fue la señal" | The agent failed mid-answer — the log has the real error |
| Says "ya gasté mi domingo" | The daily budget is spent; it resets at midnight |
| Answers but never moves | Low battery, or he simply decided not to — he is told to move little |
| Goes quiet and the LED is red | Brownout. Power-cycle, then read [Power](pi-config.md#power) |

More in [Troubleshooting](troubleshooting.md).

## Which model does what

Six models share the work, and only the first one writes what he says:

| Job | Model | Set in |
|-----|-------|--------|
| His answers | `claude-fable-5-1`, effort `low` | `AGENT_MODEL` |
| When that model is overloaded | `claude-sonnet-5` | `AGENT_FALLBACK_MODEL` |
| When the agent fails outright | `gpt-5.6-luna` | `llm = LLM(...)` |
| Deciding what to remember | `gpt-4.1-mini` | `memory_llm` |
| His voice, and hearing you | `gpt-4o-mini-tts`, `gpt-4o-transcribe` | `petronilo_voice.py` |
| Looking for something | `gpt-4.1-mini` | `LOCATOR = VisionLocator(...)` |

All but the last two live at the top of
[`examples/18_voice_active_crawler_gpt.py`](../examples/18_voice_active_crawler_gpt.py).
The wake word never leaves the Pi — that is Vosk, offline, which is why it
answers to "compra" as readily as "compa".

The fallback chain matters more than the model choice. If Anthropic is
overloaded he drops to Sonnet and keeps his tools and memory; only if the agent
fails completely does the OpenAI model answer that one turn, without tools. You
can hear the difference: no tools means no camera, no reminders, no memory
lookup.

## Who he is

His personality lives in [`examples/petronilo/SOUL.md`](../examples/petronilo/SOUL.md):
identity, voice, the albures, his limits, what he knows about his own body.
Edit that file and restart the service to change who he is. The operating
instructions — the tool descriptions, the action names — live in the script
and are a different thing; changing those changes what he *can* do, not who he
is.
