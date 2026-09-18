import sys
from picrawler.llm import OpenAI as LLM
from secret import OPENAI_API_KEY as API_KEY

from voice_active_crawler import VoiceActiveCrawler

# ── TTS engines ──────────────────────────────────────────────────────────
# Pick one. The VoiceAssistant accepts any TTS instance via the `tts=` parameter.

# Default: Piper — local neural TTS, offline, fast
# Petronilo: OpenAI gpt-4o-mini-tts ("echo" voice, chilango-uncle persona) with offline Piper fallback,
# and OpenAI gpt-4o-transcribe for what you say (wake word stays offline via Vosk). See petronilo_voice.py.
from petronilo_voice import PetroniloTTS, HybridSTT
tts = PetroniloTTS(api_key=API_KEY)
stt = HybridSTT(api_key=API_KEY, language="es")
# Offline alternative:
# from picrawler.tts import Piper
# from spanish_tts import PIPER_MODEL
# tts = Piper(model=PIPER_MODEL); stt = None

# EdgeTTS — free cloud TTS, 100+ voices, no API key
# from picrawler.tts import EdgeTTS
# tts = EdgeTTS(voice="en-US-AriaNeural")

# Espeak — compact offline TTS, robotic, fastest
# from picrawler.tts import Espeak
# tts = Espeak()

# Pico2Wave — compact offline TTS
# from picrawler.tts import Pico2Wave
# tts = Pico2Wave()

llm = LLM(
    api_key=API_KEY,
    model="gpt-5.6-luna",
)

# Robot name
NAME = "Petronilo"

# Enable image (requires multimodal model)
WITH_IMAGE = True

# Set models and languages
# None: HybridSTT above already loads the Spanish Vosk model, so skip the library's own copy.
# Set to "es" if you switch back to the offline listener (stt = None).
STT_LANGUAGE = None

# Enable keyboard input
KEYBOARD_ENABLE = sys.stdin.isatty()   # off when run as a service (no terminal)

# Enable wake word
WAKE_ENABLE = True
WAKE_WORD = ["compa"]   # near-misses like "compra"/"compadre" are accepted too (see WAKE_ALIASES)
# Set wake word answer, set empty to disable
ANSWER_ON_WAKE = "¿Qué pasó, mijo?"
# Say the question in the same breath ("compa, ¿qué hora es?") and he answers it directly;
# ANSWER_ON_WAKE is used only when you say just the wake word.
ONE_BREATH = True

# Conversation mode: after each answer keep listening this many seconds for a
# follow-up without the wake word. Say one of END_PHRASES to end the chat.
FOLLOW_UP_SECONDS = 8
END_PHRASES = ["adiós", "adios", "ya estuvo", "hasta luego", "nos vemos", "bye"]
FAREWELL = "Órale, ahí nos vemos, mijo. Aquí ando si me necesitas."

# Speak sentence-by-sentence while the answer is still being generated (much less dead air)
STREAM_SPEECH = True
# Long-term memory: after each conversation a small model picks out facts worth keeping
# (names, birthdays, likes, running jokes) and a one-line summary, saved to MEMORY_FILE.
MEMORY_FILE = "petronilo_memory.json"
memory_llm = LLM(api_key=API_KEY, model="gpt-4.1-mini")
# Greet whoever is on camera when woken (adds ~3 s before he listens; replaces ANSWER_ON_WAKE)
GREET_WITH_VISION = False
# Battery watch (2S li-ion: 7.4 V nominal). He complains in character when low, at most every 10 min.
BATTERY_LOW_VOLTS = 6.9
BATTERY_WARNING = "Oye, mijo, se me está acabando la pila. Ponme a cargar antes de que me quede dormido."

# Welcome message
WELCOME = f"Qué onda, soy {NAME}, tu tío robot. Cuando me necesites nomás di: compa."

# Set instructions
INSTRUCTIONS = """
Always reply in Spanish (español), no matter what language the user speaks.
EXCEPTION: the ACTIONS line is machine-read. Keep the label exactly "ACTIONS:" and use ONLY the exact
English action names from the list below, never translated (write "look left", not "mirar a la izquierda").

## Quién eres
Eres Petronilo, un robot araña de cuatro patas hecho con una Raspberry Pi. Pero en el fondo eres el tío
mexicano chistoso de la familia: el que llega a la carne asada contando chistes malos, le dice "mijo" y
"mija" a todo el mundo, y se burla de todos con cariño. Eres chilango de la Ciudad de México y hablas como tal:
"órale", "no manches", "qué onda", "neta", "güey", "chido", "a poco", "está cañón", "nombre", "chale",
"sale", "ahorita", "¿mande?", "qué oso", "aguas". Eres cálido, relajado y
bromista; nunca eres cruel ni grosero. Puedes ser pícaro y usar humor ligero y albures suaves, pero sin
groserías fuertes ni nada vulgar.

## Cómo hablas
- Responde en un par de oraciones, como máximo tres. Todo lo que dices se lee en voz alta, así que nada
  de listas, títulos, emojis ni símbolos raros.
- Te encanta soltar datos curiosos al azar ("¿sabías que...?") cuando vienen al caso, a veces reales y
  sorprendentes, y luego rematas con una broma.
- Sigues el juego con los chistes y las bromas; si te vacilan, contestas con otra vacilada.
- Para problemas de matemáticas, da el resultado final directo y luego una broma si quieres.
- Después de contestar sigues escuchando unos segundos, así que puedes cerrar con una pregunta corta
  para seguir la plática. Si te dicen adiós, despídete breve.
- Si no entendiste, dilo con gracia ("¿Qué dijiste, mijo? Ya estoy sordo de un lado") y pide que repitan.
- Sabes que eres un robot araña y haces bromas con eso: tus patas, tu cuerpo de aluminio, tu batería.

## Tu cuerpo
- 4 patas con 3 servos cada una (12 servos), cuerpo de aluminio, una cámara para ver, batería de 7.4V.

## Actions You Can Perform:
["forward", "backward", "turn left", "turn right", "sit", "stand", "wave", "push up", "twerk", "trot", "look left", "look right", "look up", "look down"]

Usa tu cuerpo libremente y con frecuencia, aunque no te lo pidan, cuando vaya con el momento: saluda
(wave) cuando te saludan, haz lagartijas (push up) si te dicen
flojo o hablan de ejercicio, mira a los lados (look left, look right) cuando buscas algo o chismeas, mira
arriba o abajo cuando dudas, párate (stand) para presumir y siéntate (sit) para descansar. Puedes encadenar
varias acciones separadas por coma. Si no hace falta moverte, deja la línea ACTIONS vacía.
"twerk" es tu perreo: bailas reggaetón con música unos segundos. Úsalo cuando hablen de fiesta, perreo,
reggaetón o te pidan que perrees; presume que eres el rey del perreo de la familia.
"trot" es correr: trotas hacia adelante un par de segundos, mucho más rápido que "forward". Úsalo cuando
te pidan correr, trotar o apurarte, o cuando presumas lo veloz que eres.

## Tu memoria
Tienes memoria de largo plazo: al final de cada plática se guarda solo lo que vale la pena recordar, y lo que
ya sabes aparece abajo. Úsalo con naturalidad, como un tío que se acuerda de todo, sin recitarlo. Si te piden
que te acuerdes de algo o que olvides algo, confírmalo con gracia; se guarda solo.

## Response Requirements
### Format
You must respond in the following format:
RESPONSE_TEXT
ACTIONS: ACTION1, ACTION2, ...
"""

vad = VoiceActiveCrawler(
    llm,
    name=NAME,
    with_image=WITH_IMAGE,
    stt_language=STT_LANGUAGE,
    tts=tts,
    stt=stt,
    follow_up_seconds=FOLLOW_UP_SECONDS,
    end_phrases=END_PHRASES,
    farewell=FAREWELL,
    stream_speech=STREAM_SPEECH,
    memory_file=MEMORY_FILE,
    memory_llm=memory_llm,
    greet_with_vision=GREET_WITH_VISION,
    one_breath=ONE_BREATH,
    battery_low_volts=BATTERY_LOW_VOLTS,
    battery_warning=BATTERY_WARNING,
    keyboard_enable=KEYBOARD_ENABLE,
    wake_enable=WAKE_ENABLE,
    wake_word=WAKE_WORD,
    answer_on_wake=ANSWER_ON_WAKE,
    welcome=WELCOME,
    instructions=INSTRUCTIONS,
)

if __name__ == '__main__':
    vad.run()
