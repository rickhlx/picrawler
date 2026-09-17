#!/usr/bin/env python3
from robot_hat.tts import Piper
from spanish_tts import EspeakES, PIPER_MODEL

# ── Text-to-Speech demo for PiCrawler ───────────────────────────────────
# Press Ctrl+C to exit.
# The TTS engines available in robot_hat.tts / picrawler.tts are:
#
#   Piper      — local neural TTS, offline, fast (best quality)
#   EdgeTTS    — free cloud TTS, 100+ voices, no API key
#   Espeak     — compact offline TTS, robotic, fastest
#   Pico2Wave  — compact offline TTS
#
# Just instantiate and call tts.say(text).
#   from robot_hat.tts import Piper
#   tts = Piper(model="en_US-ryan-low")        # English
#   tts = Piper(model="zh_CN-huayan-x_low")    # Chinese
#   from robot_hat.tts import EdgeTTS
#   tts = EdgeTTS(voice="en-US-AriaNeural")
#   from robot_hat.tts import Espeak, Pico2Wave
#   tts = Espeak()
#   tts = Pico2Wave()

# Choose TTS engine
USE_PIPER = True          # True=Piper, False=Espeak
TTS_MODEL = PIPER_MODEL   # Spanish Piper model (see spanish_tts.py); "en_US-ryan-low" for English

def main():
    print("=== PiCrawler Text-to-Speech Demo ===")

    if USE_PIPER:
        print(f"Engine: Piper ({TTS_MODEL})")
        tts = Piper(model=TTS_MODEL)
    else:
        print("Engine: Espeak (es-la)")
        tts = EspeakES()

    print("Type text to speak, or 'quit' to exit")
    print()

    try:
        while True:
            text = input("Text to speak: ").strip()
            if text.lower() == 'quit':
                break
            if text:
                print(f"Speaking: {text}")
                tts.say(text)
    except KeyboardInterrupt:
        print("\nExiting...")

if __name__ == "__main__":
    main()
