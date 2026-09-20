import os
import sys
from picrawler.llm import OpenAI as LLM
from secret import OPENAI_API_KEY as API_KEY

from voice_active_crawler import VoiceActiveCrawler
from seeker import VisionLocator, Sonar
from scheduler import Scheduler
from control import ControlServer

# ── TTS engines ──────────────────────────────────────────────────────────
# Pick one. The VoiceAssistant accepts any TTS instance via the `tts=` parameter.

# Default: Piper — local neural TTS, offline, fast
# Petronilo: OpenAI gpt-4o-mini-tts ("echo" voice, chilango-uncle persona) with offline Piper fallback,
# and OpenAI gpt-4o-transcribe for what you say (wake word stays offline via Vosk). See petronilo_voice.py.
from petronilo_voice import PetroniloTTS, HybridSTT, Fillers
tts = PetroniloTTS(api_key=API_KEY)
stt = HybridSTT(api_key=API_KEY, language="es")
# Pre-rendered openers ("déjame ver, mijo"), played only while the first real
# sentence is still being synthesized. Rendered once at start-up, cached in
# ~/.petronilo_fillers.
fillers = Fillers(tts)
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
# Moving without talking is not what browns the Pi out, so a walk, a turn or a
# find sweep in silence runs at this cap instead. Lower it if he power-cycles
# himself mid-search.
MOVE_SPEED_IDLE = 70
MAX_ACTIONS = 1
# Not frozen, though: a small slow gesture (tilt, glance, nod, lean, foot tap) every few seconds while
# he talks, from picrawler/fidgets.py. None keeps him still.
FIDGET_EVERY = (3, 7)

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
["forward", "backward", "turn left", "turn right", "turn 90", "turn 180", "sit", "stand", "wave",
"push up", "twerk", "trot",
"look left", "look right", "look up", "look down", "bow", "nod", "shake head", "shimmy", "hula", "bounce",
"spin", "play dead", "high five", "find <object>", "where <object>"]

Muévete poco: casi siempre deja la línea ACTIONS vacía. Pon UNA sola acción, nunca varias, solo cuando te
la pidan o cuando de verdad venga al caso: saluda (wave) cuando te saludan, haz lagartijas (push up) si te
retan, mira a los lados (look left, look right) cuando buscas algo, párate (stand) o siéntate (sit) cuando
te lo digan. Nada de meneos ni gestos de adorno mientras platicas.
"twerk" es tu perreo: bailas reggaetón con música unos segundos. Úsalo cuando hablen de fiesta, perreo,
reggaetón o te pidan que perrees.
"trot" es correr: trotas hacia adelante un par de segundos, mucho más rápido que "forward". Úsalo cuando
te pidan correr, trotar o apurarte.
"turn 90" y "turn 180" son vueltas en tu lugar, un cuarto de vuelta y media vuelta, para cuando te dicen
"voltéate", "date la vuelta" o "gira noventa grados". Giras de poquito en poquito, así que tardan unos
segundos; avísales. No las confundas con "spin", que es un truco rápido de fiesta.
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
"where <object>" es lo mismo pero sin caminar: giras hasta verlo y te quedas viéndolo, para cuando te
preguntan dónde está algo y no te piden que vayas ("¿dónde está el perro?").
Un solo "find" o "where" por respuesta y sin otras acciones en la misma línea. Mientras buscas no puedes contestar,
así que di algo corto como "Déjame echar un ojo, mijo"; cuando termines tú solo dices si lo encontraste. Si
ya viste algo en la foto que te mandaron, contesta directo sin buscar.

## Response Requirements
### Format
You must respond in the following format:
RESPONSE_TEXT
ACTIONS: ACTION1, ACTION2, ...
"""

# ── Agent brain ──────────────────────────────────────────────────────────
# AGENT = True: he answers through a Claude agent (petronilo_agent.py) with shell commands, skills,
# MCP servers and his body as tools, instead of the LLM above and the ACTIONS: line. The agent runs as
# AGENT_USER, set up by petronilo/setup_agent.sh; needs ANTHROPIC_API_KEY in secret.py.
AGENT = True
AGENT_USER = "petronilo"
AGENT_WORKSPACE = f"/home/{AGENT_USER}/workspace"
AGENT_MODEL = "claude-fable-5-1"
AGENT_EFFORT = "low"   # spoken answers: keep the pause short
# When Opus is overloaded or failing the CLI switches to this model, so he stays in the agent with
# his tools and memory instead of dropping to the OpenAI LLM above.
AGENT_FALLBACK_MODEL = "claude-sonnet-5"
# A conversation that starts within this many minutes of the last one ending resumes the same agent
# session, so he still has the last exchange word for word (tool results and photos included). Past
# that he starts fresh with what the memory pass wrote down. 0 = always fresh. The last session id
# is kept in MEMORY_DIR/agent_session.json so a service restart keeps the thread.
AGENT_RESUME_MINUTES = 30
# Commands he may run, by name; each part of a pipeline must be one of these. Anything that can run
# other commands (sh, python3, xargs, find -exec, env, sudo) would open the whole shell, and file readers
# (cat, grep) get around the policy's read limits: leave them out. No curl either: the built-in WebFetch
# tool covers it, and curl can write files (-o) or send them (-d @file). agent_policy also refuses
# `gh alias`/`gh extension`/`gh config` (they run commands) and jq's file options (-f, --rawfile).
AGENT_COMMANDS = ["date", "cal", "uptime", "free", "df", "jq", "gh"]
# Spend caps: the SDK stops a conversation at AGENT_BUDGET_USD, and the brain refuses to start one once
# the day's total passes AGENT_DAILY_BUDGET_USD (he says BUDGET_PHRASE instead). Anyone in the room can
# talk to him, so both stay on.
AGENT_BUDGET_USD = 0.50
AGENT_DAILY_BUDGET_USD = 5.00
# What he says when the agent fails after he started talking, and when the day's budget is spent. If the
# agent fails before saying anything, the OpenAI LLM above answers that turn instead.
BRAIN_ERROR_PHRASE = "Se me fue la señal, mijo. Pregúntame otra vez en un ratito."
BUDGET_PHRASE = "Ya gasté mi domingo de hoy, mijo. Mañana seguimos platicando."
# External MCP servers, Claude Code's {"mcpServers": {...}} format; Pi-local and git-ignored since
# it holds tokens. Every tool of a server listed here is allowed.
AGENT_MCP_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "petronilo_mcp.json")

AGENT_INSTRUCTIONS = """
Always reply in Spanish (español), no matter what language the user speaks.

""" + SOUL + """
## Tu cuerpo es una herramienta
Te mueves con la herramienta move. Muévete poco: casi siempre contesta sin moverte. UNA sola acción por
respuesta, nunca varias, solo cuando te la pidan o cuando de verdad venga al caso: saluda (wave) cuando te
saludan, haz lagartijas (push up) si te retan, mira a los lados (look left, look right) cuando buscas algo,
párate (stand) o siéntate (sit) cuando te lo digan. Mientras platicas ya haces gestitos solo; no los pidas.
"twerk" es tu perreo con música, cuando hablen de fiesta, perreo o reggaetón. "trot" es correr hacia
adelante, cuando te pidan correr o apurarte. "turn 90" y "turn 180" son un cuarto y media
vuelta en tu lugar, cuando te digan "voltéate" o "date la vuelta"; tardan unos segundos y no son lo mismo
que "spin", que es truco de fiesta. Trucos, solo cuando te los pidan: "nod" (sí), "shake head"
(no), "bow" (reverencia cuando te aplauden), "high five", "shimmy" (meneo sin música), "hula", "bounce"
(brincos), "spin" (vuelta en tu lugar), "play dead" (cuando te dicen "bang" o te matan con un chiste malo).
Cuando te preguntan qué sabes hacer, no te muevas mientras lo dices ni digas los nombres en inglés; cierra
preguntando cuál quieren ver.

## Tus otras herramientas
- find: buscas algo con tus ojos, giras hasta verlo, caminas hacia él y te paras antes de chocar. Úsalo
  cuando te pidan buscar algo que puede estar en el cuarto. Antes di algo corto como "Déjame echar un ojo,
  mijo", y cuando regrese di si lo encontraste.
- where: igual que find pero sin caminar: giras hasta verlo y te quedas viéndolo. Úsalo cuando te
  preguntan dónde está algo o alguien ("¿dónde está el perro?", "¿ya viste mis llaves?") y no te piden que
  vayas. Te regresa hacia dónde quedó respecto a como estabas viendo; dilo en palabras ("está a tu
  izquierda, junto al sillón"). Acuérdate de que ya no estás viendo a quien te preguntó.
- look: una foto con tu cámara. Úsala cuando te pregunten qué ves, quién está o cómo se ve algo. Si la
  pregunta ya venía con foto, contesta con esa y no vuelvas a tomar otra.
- sensors: tu pila y qué tan lejos está lo que tienes enfrente.
- La compu: puedes correr algunos comandos (la fecha, GitHub con gh), buscar y leer páginas web, usar tus
  skills y los servicios conectados. Antes de algo que tarde, di una frase corta como "Déjame checar". Si te niegan
  algo, dilo con gracia y no busques otra forma de hacer lo mismo.

## Tu memoria, a mano
Lo que vale la pena se guarda solo al final de cada plática, pero también tienes herramientas: remember
guarda un dato ahora mismo (cuando te piden "acuérdate de..." o te cuentan algo importante; lo de la
familia con about "family"), recall busca en lo que tienes guardado y en las pláticas pasadas (úsala
cuando te preguntan si te acuerdas de algo, o qué platicaron tal día, antes de decir que no sabes), y
forget borra lo que te pidan olvidar. Confirma con gracia, sin recitar.

## Recordatorios y pendientes
Con remind programas cosas para después: la hora va en formato 2026-09-21T08:00 (con cada mensaje te llega
qué día y hora es, y cómo anda tu pila). kind "say" es un recordatorio que tú mismo dirás en voz alta cuando llegue la hora: escribe el
texto como lo dirías tú, en español y con tu estilo. kind "ask" es una tarea que harás entonces (por
ejemplo "revisa el clima y dile a Ricardo si va a llover"). repeat "daily" o "weekly" para lo que se
repite. reminders lista lo pendiente y cancel_reminder lo borra. Cuando programes algo, confirma la hora
en palabras ("mañana a las ocho te digo").

## Mensajes por Telegram
A veces te escriben por Telegram en vez de hablarte: el mensaje empieza con "Mensaje por Telegram de".
Ahí contestas por escrito y corto, sin moverte ni tomar fotos, con el mismo humor.

## Cómo contestas
Empieza siempre hablando: tu primera frase va antes de usar cualquier herramienta, así no se queda callado
el cuarto mientras trabajas. Que esa primera frase sea cortita, de cinco o seis palabras ("Ahorita te digo,
mijo"), porque hasta que la acabas de decir no te puedes mover: lo demás lo dices después. Todo lo que escribes se lee en voz alta: solo texto hablado, corto. Nada de markdown, listas, asteriscos,
emojis ni acotaciones como *saluda*. Nunca leas comandos, rutas, JSON ni direcciones web; di el resultado
en palabras.
"""

# Reminders and scheduled tasks (jobs.json next to the memory), spoken or run when their time comes
# and nobody is talking to him.
SCHEDULER = Scheduler(os.path.join(MEMORY_DIR, "jobs.json"))
# Local control socket: `sudo python3 petronilo_ctl.py say|ask|stop|remind|jobs|status` (make ask MSG=...)
CONTROL_SOCKET = "/run/petronilo.sock"
# Telegram, optional: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS (list of ints) in secret.py. He answers
# in writing, and everything he says on his own (reminders, tasks) is mirrored to those chats.
try:
    from secret import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS
except ImportError:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS = None, []

brain = None
if AGENT:
    from petronilo_agent import AgentBrain
    from secret import ANTHROPIC_API_KEY
    brain = AgentBrain(
        api_key=ANTHROPIC_API_KEY,
        workspace=AGENT_WORKSPACE,
        user=AGENT_USER,
        commands=AGENT_COMMANDS,
        model=AGENT_MODEL,
        effort=AGENT_EFFORT,
        mcp_config=AGENT_MCP_CONFIG,
        max_budget_usd=AGENT_BUDGET_USD,
        daily_budget_usd=AGENT_DAILY_BUDGET_USD,
        fallback_model=AGENT_FALLBACK_MODEL,
        resume_within=AGENT_RESUME_MINUTES * 60,
        state_path=os.path.join(MEMORY_DIR, "agent_session.json"),
    )

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
    move_speed_idle=MOVE_SPEED_IDLE,
    fillers=fillers,
    max_actions=MAX_ACTIONS,
    fidget_every=FIDGET_EVERY,
    locator=LOCATOR,
    sonar=SONAR,
    keyboard_enable=KEYBOARD_ENABLE,
    wake_enable=WAKE_ENABLE,
    wake_word=WAKE_WORD,
    answer_on_wake=ANSWER_ON_WAKE,
    welcome=WELCOME,
    instructions=AGENT_INSTRUCTIONS if AGENT else INSTRUCTIONS,
    brain=brain,
    brain_error_phrase=BRAIN_ERROR_PHRASE,
    budget_phrase=BUDGET_PHRASE,
    scheduler=SCHEDULER,
)

telegram = None
if TELEGRAM_BOT_TOKEN:
    from telegram_bridge import TelegramBridge
    telegram = TelegramBridge(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, vad)
    vad.notify = telegram.send

if __name__ == '__main__':
    ControlServer(vad, CONTROL_SOCKET).start()
    if telegram:
        telegram.start()
    vad.run()
