import os
import sys
from picrawler.llm import OpenAI as LLM
from secret import OPENAI_API_KEY as API_KEY

from voice_active_crawler import VoiceActiveCrawler
from seeker import VisionLocator, Sonar

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

# Conversation mode: after each answer keep listening this many seconds for a
# follow-up without the wake word. Say one of END_PHRASES to end the chat.
FOLLOW_UP_SECONDS = 8
END_PHRASES = ["adiós", "adios", "ya estuvo", "hasta luego", "nos vemos", "bye"]
FAREWELL = "Órale, ahí nos vemos, mijo. Aquí ando si me necesitas."

# Speak sentence-by-sentence while the answer is still being generated (much less dead air)
STREAM_SPEECH = True
# Long-term memory: after each conversation a small model picks out facts worth keeping
# (names, birthdays, likes, running jokes) and a one-line summary. Saved as Markdown in MEMORY_DIR,
# laid out like OpenClaw's memory: USER.md (the family), MEMORY.md (the rest), memory/<date>.md
# (daily notes). Next to this script, whatever directory he is started from.
MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "petronilo_memory")
memory_llm = LLM(api_key=API_KEY, model="gpt-4.1-mini")
# Greet whoever is on camera when woken (adds ~3 s before he listens; replaces ANSWER_ON_WAKE)
GREET_WITH_VISION = False
# Battery watch (2S li-ion: 7.4 V nominal). He complains in character when low, at most every 10 min,
# and refuses the moves that drive every servo at once. The resting voltage overstates what is left
# under load: the Pi browned out at 7.43 V, so the cutoff sits well above the 6.9 V pack floor.
BATTERY_LOW_VOLTS = 7.3
BATTERY_WARNING = "Oye, mijo, se me está acabando la pila. Ponme a cargar antes de que me quede dormido."
# Calm body while he talks: moving and speaking at once browns the Pi out (docs/pi-config.md, Power).
# Every move is capped at this servo speed (0-100) and each reply runs at most MAX_ACTIONS actions.
MOVE_SPEED_LIMIT = 40
MAX_ACTIONS = 1

# "find <object>": the camera frames go to a small vision model, the ultrasonic
# sensor on D2/D3 stops him short of whatever is in front.
LOCATOR = VisionLocator(API_KEY, model="gpt-4.1-mini")
SONAR = Sonar()

# Welcome message
WELCOME = f"Qué onda, soy {NAME}, tu tío robot. Cuando me necesites nomás di: compa."

# Who he is (personality, voice, albures, limits, body, memory) lives in petronilo/SOUL.md, laid out
# like OpenClaw's SOUL.md; edit it there and restart. What follows is how he operates: the action
# names the code dispatches on and the reply format parse_response expects.
SOUL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "petronilo", "SOUL.md")
with open(SOUL_FILE, encoding="utf-8") as f:
    SOUL = f.read()

INSTRUCTIONS = """
Always reply in Spanish (español), no matter what language the user speaks.
EXCEPTION: the ACTIONS line is machine-read. Keep the label exactly "ACTIONS:" and use ONLY the exact
English action names from the list below, never translated (write "look left", not "mirar a la izquierda").

""" + SOUL + """
## Actions You Can Perform:
["forward", "backward", "turn left", "turn right", "sit", "stand", "wave", "push up", "twerk", "trot",
"look left", "look right", "look up", "look down", "bow", "nod", "shake head", "shimmy", "hula", "bounce",
"spin", "play dead", "high five", "find <object>"]

Muévete poco: casi siempre deja la línea ACTIONS vacía. Pon UNA sola acción, nunca varias, solo cuando te
la pidan o cuando de verdad venga al caso: saluda (wave) cuando te saludan, haz lagartijas (push up) si te
retan, mira a los lados (look left, look right) cuando buscas algo, párate (stand) o siéntate (sit) cuando
te lo digan. Nada de meneos ni gestos de adorno mientras platicas.
"twerk" es tu perreo: bailas reggaetón con música unos segundos. Úsalo cuando hablen de fiesta, perreo,
reggaetón o te pidan que perrees.
"trot" es correr: trotas hacia adelante un par de segundos, mucho más rápido que "forward". Úsalo cuando
te pidan correr, trotar o apurarte.
Tus trucos de fiesta, solo cuando te los pidan: "nod" asiente (sí) y "shake head" niega (no). "bow" es una
reverencia cuando te aplauden, te agradecen o terminas un truco. "high five" levanta una pata para chocar
esos cinco. "shimmy" es un meneo corto para cuando te dicen que bailes sin música; "hula" son círculos de
cadera. "bounce" son brincos de emoción. "spin" es dar una vuelta en tu lugar. "play dead" te haces el
muerto con las patas para arriba, para cuando te "matan" con un chiste malo o te dicen "bang".
Cuando te preguntan qué sabes hacer, no te muevas mientras lo dices (y nunca digas los nombres en inglés en
voz alta); cierra preguntando cuál quieren ver, y cuando te lo pidan, hazlo.

## Buscar cosas
"find <object>" es buscar algo con tus ojos: giras en tu lugar mirando con la cámara hasta verlo, caminas
hacia él y te paras antes de chocar. Úsalo cuando te pidan buscar o encontrar algo que puede estar en el
cuarto ("búscame las llaves", "¿dónde está la pelota?", "encuentra a mi gato"). Escribe el objeto en
español, corto, con artículo y lo que lo distingue: "find la taza roja", "find tus llaves", "find al gato".
Un solo "find" por respuesta y sin otras acciones en la misma línea. Mientras buscas no puedes contestar,
así que di algo corto como "Déjame echar un ojo, mijo"; cuando termines tú solo dices si lo encontraste. Si
ya viste algo en la foto que te mandaron, contesta directo sin buscar.

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
    memory_dir=MEMORY_DIR,
    memory_llm=memory_llm,
    greet_with_vision=GREET_WITH_VISION,
    battery_low_volts=BATTERY_LOW_VOLTS,
    battery_warning=BATTERY_WARNING,
    move_speed_limit=MOVE_SPEED_LIMIT,
    max_actions=MAX_ACTIONS,
    locator=LOCATOR,
    sonar=SONAR,
    keyboard_enable=KEYBOARD_ENABLE,
    wake_enable=WAKE_ENABLE,
    wake_word=WAKE_WORD,
    answer_on_wake=ANSWER_ON_WAKE,
    welcome=WELCOME,
    instructions=INSTRUCTIONS,
)

if __name__ == '__main__':
    vad.run()
