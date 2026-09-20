# Making him feel faster

Petronilo answers in about two seconds and finishes a tool-using answer in
about five, measured on a Mac. On the Pi it is slower. This is where that time
goes, what has been done about it, and what is left.

## The path a question takes

```
wake word (offline, Vosk)      ~0      never leaves the Pi
  -> record until you stop talking
  -> STT round trip            network  gpt-4o-transcribe
  -> agent first token         network  claude-fable-5-1, session already open
  -> FIRST SENTENCE TTS        network  gpt-4o-mini-tts, synthesized to a file
  -> playback starts                    <- this is when he "answers"
```

Everything after the first sentence is hidden: `SpeechPipeline` synthesizes the
next sentence while the current one plays, and the model is usually still
writing. So the felt latency is the STT hop plus the first sentence's TTS, and
almost nothing else.

## What is already done

- The agent session opens at the wake word, so the CLI's start-up overlaps you
  talking, and the next session is pre-warmed when a conversation ends.
- MCP tools load up front (`ENABLE_TOOL_SEARCH=false`): no turn spent
  discovering tools.
- The system prompt is byte-stable — date, time, battery and distance arrive
  through a per-turn hook — so it stays in the prompt cache.
- He speaks a sentence *before* calling any tool, so the room is never silent
  while he works.
- Visual questions carry the camera frame with the question, so "¿qué ves?"
  costs no extra `look` round trip.
- Speech streams sentence by sentence rather than waiting for the whole answer.

### Added in this pass

**Pre-rendered openers.** `Fillers` in `petronilo_voice.py` renders half a
dozen short phrases once ("déjame ver, mijo", "ahorita te digo") into
`~/.petronilo_fillers` and `SpeechPipeline` plays one *only* if the real first
sentence is not ready within 0.7 s. It goes through the same play worker, so it
can never overlap the answer, and on a fast turn you never hear it. This does
not make anything faster; it removes the silence, which is the part people
notice.

**Connections stay open.** `VisionLocator` and the transcription calls now
reuse a `requests.Session`. A `find` sweep is a dozen vision calls, and it was
paying a fresh TLS handshake for each one.

**The sonar reading rides along.** It is read in the background at the wake
word and included in the per-turn context, like the battery already was, so
"¿qué tan lejos está la pared?" no longer costs a `sensors` round trip.

**A short first sentence.** The prompt now pins the opening line to five or six
words. It is the only sentence on the critical path, and TTS time scales with
length.

**He talks faster.** The voice instructions ask for an agile pace — the same
character, less drag between words.

**He moves faster when he is not talking.** `MOVE_SPEED_IDLE` (70) applies
whenever nothing is playing, while `MOVE_SPEED_LIMIT` (40) still applies while
he speaks. The cap exists because the servos and the speaker amp share one 3 A
rail; it is doing both at once that browns the Pi out. A `find` sweep, a
scheduled move or a half turn in silence now runs at the higher cap.

## What is left

**Trust Vosk for short utterances.** Vosk already listens offline for the wake
word and the end of speech. For "párate" or "date la vuelta" its transcript is
usually good enough, so the OpenAI STT call could be skipped when the utterance
is short and Vosk is confident, and kept for anything longer. This is the
biggest remaining win on the input side.

**Barge-in.** The one that changes how he *feels* rather than how fast he is:
cutting him off mid-answer. `SpeechPipeline.cancel()` drops everything queued
but cannot stop the sentence already playing — `AudioPlayer` has no stop call —
and nothing listens while he speaks. Doing it properly needs a stoppable player
(chunked playback, or another audio backend) and the microphone open during
speech with the wake word as the interrupt. Largest job here, and the one a
person in the room would notice first.

**Wi-Fi power save.** Now disabled per-connection for networks added with
`make wifi` (`powersave=2`). Existing profiles predate that: check with
`nmcli -f 802-11-wireless.powersave connection show <name>`.

## What will not help

- A bigger or smaller model. He is already on `low` effort, and the model is
  not the bottleneck; the two network hops around it are.
- Moving the agent off the Pi. The CLI's start-up is already off the critical
  path.
- Caching answers. Every turn carries a different time, battery and memory
  state, and the prompt cache already covers the expensive, stable part.

## How to measure

Each conversation logs its cost, turn count and duration to the journal:

```bash
journalctl -u petronilo --since today | grep -i "coste\|turnos\|agente"
```

Get a before number from the same place before claiming a change helped. The
honest measure is wall clock in the room: how long a person stands there before
hearing anything.
