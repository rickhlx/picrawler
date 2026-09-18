from picrawler.voice_assistant import VoiceAssistant
from picrawler import Picrawler
from memory import Memory
import time
import queue
import threading
import os
import re
import sys


class VoiceActiveCrawler(VoiceAssistant):

    ACTION_MAP = {
        "forward":      ("do_action", {"motion_name": "forward", "speed": 70}),
        "backward":     ("do_action", {"motion_name": "backward", "speed": 70}),
        "turn left":    ("do_action", {"motion_name": "turn left", "speed": 70}),
        "turn right":   ("do_action", {"motion_name": "turn right", "speed": 70}),
        "move left":    ("self:sidestep", {"direction": 1}),    # sideways, facing the same way
        "move right":   ("self:sidestep", {"direction": -1}),
        "sit":          ("do_action", {"motion_name": "sit", "step": 1, "speed": 50}),
        "stand":        ("do_action", {"motion_name": "stand", "step": 1, "speed": 50}),
        "wave":         ("do_action", {"motion_name": "wave", "step": 1, "speed": 60}),
        "push up":      ("do_action", {"motion_name": "push_up", "step": 1, "speed": 50}),
        "twerk":        ("self:party", {"seconds": 12}),   # reggaeton routine from twerk.py
        "trot":         ("self:trot", {"half_cycles": 10}),  # fast diagonal-pair gait, forward
        "look left":    ("do_action", {"motion_name": "look_left", "step": 1, "speed": 60}),
        "look right":   ("do_action", {"motion_name": "look_right", "step": 1, "speed": 60}),
        "look up":      ("do_action", {"motion_name": "look_up", "step": 1, "speed": 60}),
        "look down":    ("do_action", {"motion_name": "look_down", "step": 1, "speed": 60}),
    }

    # Movement actions take a step count ("forward 4"): the kwarg it sets,
    # how many steps when the model gives none, and the most it may ask for.
    STEP_ACTIONS = {"forward": "step", "backward": "step", "turn left": "step", "turn right": "step",
                    "move left": "steps", "move right": "steps"}
    DEFAULT_STEPS = 3
    MAX_STEPS = 8

    def __init__(self, *args, stt=None, follow_up_seconds=0, end_phrases=None, farewell="",
                 stream_speech=True, memory_file=None, memory_llm=None, greet_with_vision=False, one_breath=False,
                 battery_low_volts=6.9, battery_warning="", **kwargs):
        self.action_queue = queue.Queue()
        self._action_busy = threading.Event()
        # Speak sentence-by-sentence while the LLM is still streaming (needs PetroniloTTS)
        self.stream_speech = stream_speech
        self._spoken_result = None
        # Long-term memory, learned from each conversation once it ends (needs memory_llm)
        memory_file = memory_file or os.path.join(os.path.dirname(os.path.abspath(__file__)), "petronilo_memory.json")
        self.memory = Memory(memory_file, llm=memory_llm, name=kwargs.get("name", "the robot"))
        self._transcript = []     # (role, text) turns of the current conversation
        self._recording = True    # off for turns that are not part of the conversation
        # "Compa, ¿qué hora es?" in one breath: answer it directly instead of
        # replying to the wake word and listening again.
        self.one_breath = one_breath
        self._wake_utterance = None   # set by the wake-word thread when the question came with it
        self._ignored = False         # the last reply was IGNORE_REPLY
        # Vision greeting on wake (opt-in: adds ~3s before listening)
        self.greet_with_vision = greet_with_vision
        if greet_with_vision:
            kwargs["answer_on_wake"] = ""
        # Battery watch
        self.battery_low_volts = battery_low_volts
        self.battery_warning = battery_warning
        self._last_battery_warning = 0.0
        # Conversation mode: after answering, keep listening this many seconds
        # for the next question without requiring the wake word (0 = off).
        self.follow_up_seconds = follow_up_seconds
        self.end_phrases = [self._norm_text(x) for x in (end_phrases or [])]
        self.farewell = farewell
        self._action_thread = None
        self._action_running = False
        try:
            super().__init__(*args, **kwargs)
        except Exception as e:
            self._handle_init_error(e)
            raise
        # LLM.add_message trims history from the front once it passes max_messages,
        # which drops the system prompt. Trim it ourselves instead and keep the
        # system prompt pinned at index 0 (see _refresh_system_prompt).
        self._system_msg = self.llm.messages[0]
        self._history_limit = self.llm.max_messages
        self.llm.max_messages = sys.maxsize
        self._init_crawler()
        if stt is not None:
            # Replace the library's STT (e.g. with HybridSTT from petronilo_voice)
            self.stt = stt
            self.stt.set_wake_words(self.wake_word)
        # The small Vosk models often garble short wake phrases; match loosely
        # (accent-insensitive, wake phrase anywhere in the transcript) instead
        # of the library's exact whole-transcript comparison.
        self.stt.heard_wake_word = self._fuzzy_heard_wake_word

    @staticmethod
    def _handle_init_error(error):
        err_msg = str(error)
        if 'PortAudioError' in type(error).__name__ or 'query_devices' in err_msg:
            print("=" * 55)
            print("  No microphone detected!")
            print("  The voice assistant requires a microphone for")
            print("  speech recognition and wake word detection.")
            print()
            print("  Options:")
            print("  1. Connect a USB microphone to the Raspberry Pi")
            print("  2. Connect an I2S MEMS mic and enable it:")
            print("     Edit /boot/firmware/config.txt")
            print('     Uncomment: dtparam=i2s=on')
            print("=" * 55)
        else:
            print(f"VoiceActiveCrawler init failed: {err_msg}")

    def _init_crawler(self):
        try:
            self.crawler = Picrawler()
            time.sleep(1)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Picrawler: {e}")

    # ── lifecycle overrides ──────────────────────────────────────────

    def on_start(self):
        self._report_battery(startup=True)
        self._action_running = True
        self._action_thread = threading.Thread(
            target=self._action_handler, daemon=True
        )
        self._action_thread.start()
        self.crawler.do_action("sit", speed=50)

    def before_listen(self):
        self.crawler.do_action("sit", speed=50)

    def on_wake(self):
        self._report_battery()
        if self.greet_with_vision:
            self._vision_greeting()

    def before_think(self, text):
        self._refresh_system_prompt()
        if self._recording and text:
            self._transcript.append(("user", text.removeprefix(self.FOLLOW_UP_TAG)))

    def after_think(self, text):
        self._ignored = self._is_ignored(text)
        if not self._recording:
            return
        if self._ignored:
            # overheard, not said to him: keep it out of memory too
            if self._transcript and self._transcript[-1][0] == "user":
                self._transcript.pop()
        elif text:
            self._transcript.append(("assistant", self._ACTIONS_RE.split(text, maxsplit=1)[0].strip()))

    # Follow-up turns (no wake word) are sent with FOLLOW_UP_TAG; the prompt tells
    # the model to reply IGNORE_REPLY alone when such a turn was not meant for it.
    FOLLOW_UP_TAG = "(sin decir tu nombre) "
    IGNORE_REPLY = "IGNORAR"
    MAX_IGNORED = 2   # overheard turns in a row before going back to the wake word

    def _is_ignored(self, text):
        return (text or "").strip().upper().startswith(self.IGNORE_REPLY)

    def _refresh_system_prompt(self):
        msgs = self.llm.messages
        history = [m for m in msgs if m is not self._system_msg][-(self._history_limit - 1):]
        msgs[:] = [self._system_msg] + history
        self._system_msg["content"] = self.instructions + self.memory.prompt_section()

    # Spanish (and a few loose English) names the LLM may emit -> ACTION_MAP keys
    ACTION_ALIASES = {
        "adelante": "forward", "avanzar": "forward", "avanza": "forward",
        "hacia adelante": "forward", "caminar": "forward", "camina": "forward",
        "atrás": "backward", "atras": "backward", "retroceder": "backward",
        "retrocede": "backward", "hacia atrás": "backward", "hacia atras": "backward",
        "girar a la izquierda": "turn left", "gira a la izquierda": "turn left",
        "izquierda": "turn left", "voltear a la izquierda": "turn left",
        "girar a la derecha": "turn right", "gira a la derecha": "turn right",
        "derecha": "turn right", "voltear a la derecha": "turn right",
        "moverse a la izquierda": "move left", "muévete a la izquierda": "move left",
        "muevete a la izquierda": "move left", "hacerse a la izquierda": "move left",
        "hazte a la izquierda": "move left", "de lado a la izquierda": "move left",
        "strafe left": "move left", "step left": "move left", "sidestep left": "move left",
        "moverse a la derecha": "move right", "muévete a la derecha": "move right",
        "muevete a la derecha": "move right", "hacerse a la derecha": "move right",
        "hazte a la derecha": "move right", "de lado a la derecha": "move right",
        "strafe right": "move right", "step right": "move right", "sidestep right": "move right",
        "sentarse": "sit", "siéntate": "sit", "sientate": "sit", "sentado": "sit",
        "pararse": "stand", "párate": "stand", "parate": "stand", "levantarse": "stand",
        "levántate": "stand", "levantate": "stand", "de pie": "stand", "ponerse de pie": "stand",
        "saludar": "wave", "saluda": "wave", "saludo": "wave",
        "lagartijas": "push up", "lagartija": "push up", "flexiones": "push up",
        "flexión": "push up", "hacer lagartijas": "push up", "push ups": "push up", "pushup": "push up",
        "perrear": "twerk", "perrea": "twerk", "perreo": "twerk", "twerkear": "twerk", "twerkea": "twerk",
        "twerking": "twerk", "modo fiesta": "twerk", "fiesta": "twerk", "reggaeton": "twerk",
        "reguetón": "twerk", "regueton": "twerk", "bailar reggaeton": "twerk", "bailar reguetón": "twerk",
        "trotar": "trot", "trota": "trot", "trote": "trot", "correr": "trot", "corre": "trot",
        "carrera": "trot", "run": "trot", "running": "trot", "jog": "trot",
        "mirar a la izquierda": "look left", "mira a la izquierda": "look left", "ver a la izquierda": "look left",
        "mirar a la derecha": "look right", "mira a la derecha": "look right", "ver a la derecha": "look right",
        "mirar arriba": "look up", "mira arriba": "look up", "mirar hacia arriba": "look up",
        "mirar abajo": "look down", "mira abajo": "look down", "mirar hacia abajo": "look down",
        "parar": "stop", "detenerse": "stop", "detente": "stop", "alto": "stop", "quieto": "stop",
        "ninguna": "stop", "ninguno": "stop", "nada": "stop", "none": "stop",
    }

    def normalize_action(self, action):
        a = action.strip().strip('.;:"\'[]()').lower()
        if a in self.ACTION_MAP or a == "stop":
            return a
        if a in self.ACTION_ALIASES:
            return self.ACTION_ALIASES[a]
        a2 = a.replace("_", " ")
        if a2 in self.ACTION_MAP:
            return a2
        return a

    _COUNT_RE = re.compile(r"^(.*?)\s*(?:x\s*)?(\d+)\s*(?:x|times|veces|pasos|steps)?$")

    def _parse_action(self, token):
        """"forward 4" / "forward x4" -> ("forward", 4); a count only matters for STEP_ACTIONS."""
        m = self._COUNT_RE.match(token.strip().strip('.;:"\'[]()'))
        name, count = (m.group(1), int(m.group(2))) if m else (token, None)
        action = self.normalize_action(name)
        if action not in self.STEP_ACTIONS:
            return action, 1
        return action, max(1, min(self.DEFAULT_STEPS if count is None else count, self.MAX_STEPS))

    def parse_response(self, text):
        if self._spoken_result is not None and text == self._spoken_result:
            # Streaming think() already spoke this and queued its actions.
            self._spoken_result = None
            return ""
        if self._is_ignored(text):
            return ""   # not meant for him: no words, no actions
        # Accept "ACTIONS:" or a translated "ACCIONES:" label, any case.
        result = re.split(r'\n?\s*(?:ACTIONS|ACCIONES|Acciones|Actions)\s*:\s*', text.strip(), maxsplit=1)

        response_text = result[0].strip()
        if len(result) > 1:
            actions_str = result[1].strip()
            if actions_str:
                actions = [self._parse_action(a) for a in re.split(r'\s*[,;]\s*', actions_str) if a.strip()]
            else:
                actions = [('stop', 1)]
        else:
            actions = [('stop', 1)]

        for action in actions:
            self.action_queue.put(action)

        return response_text

    def before_say(self, text):
        pass

    def after_say(self, text):
        pass  # round wrap-up (wait for actions, sit) happens in on_finish_a_round

    def _finish_round_motion(self):
        self._wait_actions_done()
        self.crawler.do_action("sit", speed=50)

    def on_stop(self):
        self._action_running = False
        # a conversation cut short by Ctrl-C: learn from it before exiting
        transcript, self._transcript = self._transcript, []
        self.memory.learn(transcript)
        self.crawler.do_action("sit", speed=50)

    # ── wake word (fuzzy) ─────────────────────────────────────────────

    @staticmethod
    def _norm_text(t):
        import unicodedata
        t = unicodedata.normalize("NFD", (t or "").lower())
        return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())

    def _fuzzy_heard_wake_word(self, print_callback=lambda x: print(f"heard: \x1b[K{x}", end="\r", flush=True)):
        result = self.stt.listen(stream=False)
        if result is None:
            return False
        print_callback(result)
        heard = self._norm_text(result)
        for w in (self.stt.wake_words or []):
            if self._wake_rest(self._norm_text(w), heard) is not None:
                self._wake_utterance = result if self.one_breath and len(self._extra_words(heard)) >= 2 else None
                return True
        return False

    # What the small Spanish Vosk model tends to hear for each wake word.
    WAKE_ALIASES = {
        "compa": ("compa", "compra", "comprar", "compacta", "compadre", "con pa", "com"),
    }

    def _wake_rest(self, wake, heard):
        """What was heard around the wake word, or None if the wake word is not there."""
        for pat in (wake,) + tuple(self._norm_text(a) for a in self.WAKE_ALIASES.get(wake, ())):
            if len(pat) >= 5:
                i = heard.find(pat)
                if i >= 0:
                    return heard[:i] + " " + heard[i + len(pat):]
            else:
                m = re.search(r"\b" + re.escape(pat) + r"\b", heard)
                if m:
                    return heard[:m.start()] + " " + heard[m.end():]
        return None

    # said around the wake word without being a question ("oye compa")
    WAKE_FILLERS = {"oye", "hey", "ey", "eh", "este", "a", "y", "o"}

    def _extra_words(self, text):
        """Words in text besides the wake word and fillers."""
        heard = self._norm_text(text)
        for w in (self.stt.wake_words or []):
            rest = self._wake_rest(self._norm_text(w), heard)
            if rest is not None:
                heard = rest
                break
        return [x for x in heard.split() if x not in self.WAKE_FILLERS]

    # ── streaming speech: talk while the LLM is still writing ────────

    _ACTIONS_RE = re.compile(r"\n?\s*(?:ACTIONS|ACCIONES|Acciones|Actions)\s*:")
    _HOLD_BACK = 12   # chars kept unspoken until we know they are not the start of "ACTIONS:"

    def think(self, text, disable_image=False):
        if not self.stream_speech or not hasattr(self.tts, "instructions"):
            return super().think(text, disable_image=disable_image)
        from petronilo_voice import SpeechPipeline
        self.before_think(text)
        image_path = None
        if self.with_image and not disable_image:
            image_path = "./img_input.jpeg"
            self.capture_image(image_path)
        kwargs = {"image_path": image_path, "stream": True}
        if self.disable_think:
            kwargs["think"] = False
        response = self.llm.prompt(text, **kwargs)
        pipeline = SpeechPipeline(self.tts)
        llm_text, spoken_upto, speaking = "", 0, True
        undecided = True   # until the reply can no longer turn out to be IGNORE_REPLY
        try:
            for word in response:
                if not self.running:
                    break
                if not word:
                    continue
                print(word, end="", flush=True)
                llm_text += word
                if not speaking:
                    continue
                if undecided:
                    head = llm_text.lstrip().upper()
                    if head.startswith(self.IGNORE_REPLY):
                        speaking = False
                        continue
                    if self.IGNORE_REPLY.startswith(head):
                        continue
                    undecided = False
                m = self._ACTIONS_RE.search(llm_text)
                if m:
                    pipeline.feed(llm_text[spoken_upto:m.start()])
                    speaking = False
                else:
                    safe = len(llm_text) - self._HOLD_BACK
                    if safe > spoken_upto:
                        pipeline.feed(llm_text[spoken_upto:safe])
                        spoken_upto = safe
            print("")
            if speaking:
                pipeline.feed(llm_text[spoken_upto:])
            result = llm_text.strip()
            self.after_think(result)
            # queue actions now so the body moves while he is still talking
            self._queue_actions(result)
            self._spoken_result = result
        finally:
            pipeline.finish()
        return result

    def _queue_actions(self, text):
        saved = self._spoken_result
        self._spoken_result = None
        try:
            VoiceActiveCrawler.parse_response(self, text)
        finally:
            self._spoken_result = saved

    # ── memory ────────────────────────────────────────────────────────

    def _end_conversation(self):
        transcript, self._transcript = self._transcript, []
        if transcript:
            # one LLM call; off the main loop so the next wake word is not delayed
            threading.Thread(target=self.memory.learn, args=(transcript,), daemon=True).start()

    # ── vision greeting on wake (opt-in) ─────────────────────────────

    def _vision_greeting(self):
        self._recording = False
        try:
            prompt = ("Te acaban de llamar. Mira la foto y saluda en UNA frase corta y chistosa a quien veas "
                      "o a lo que veas (si no ves a nadie, di algo gracioso al respecto). Sin línea ACTIONS.")
            greeting = self.think(prompt, disable_image=False)
            if greeting and self._spoken_result != greeting:
                self.tts.say(self.parse_response(greeting) or greeting)
            self._spoken_result = None
        except Exception as e:
            print(f"(saludo con cámara falló: {e})")
        finally:
            self._recording = True

    # ── battery ───────────────────────────────────────────────────────

    def battery_voltage(self):
        try:
            from robot_hat.device import get_battery_voltage
        except Exception:
            from robot_hat import get_battery_voltage
        try:
            return float(get_battery_voltage())
        except Exception:
            return None

    def _report_battery(self, startup=False):
        v = self.battery_voltage()
        if v is None:
            return
        if startup:
            print(f"Batería: {v:.2f} V")
        if v < self.battery_low_volts and time.time() - self._last_battery_warning > 600:
            self._last_battery_warning = time.time()
            print(f"(batería baja: {v:.2f} V)")
            if self.battery_warning:
                self.tts.say(self.battery_warning)

    # ── party (twerk.py) ──────────────────────────────────────────────

    def party(self, seconds=12):
        v = self.battery_voltage()
        if v is not None and v < self.battery_low_volts:
            print(f"(sin pila para perrear: {v:.2f} V)")
            return
        from twerk import party
        party(self.crawler, seconds=seconds, speed=70, volume=90)

    SIDESTEP_MM = 20   # sideways travel per half cycle; 23_trot.py allows up to 30

    def sidestep(self, steps=3, direction=1):
        # The crawl gaits have no sideways step, so this is a slow trot with only
        # strafe: one step = both diagonal pairs = 2 half cycles. direction 1 = left.
        v = self.battery_voltage()
        if v is not None and v < self.battery_low_volts:
            print(f"(sin pila para moverse de lado: {v:.2f} V)")
            return
        self.crawler.trot(half_cycles=2 * steps, stride=0, strafe=direction * self.SIDESTEP_MM, speed=80)

    def trot(self, half_cycles=10):
        # every servo moves on every frame: same current draw worry as the twerk
        v = self.battery_voltage()
        if v is not None and v < self.battery_low_volts:
            print(f"(sin pila para trotar: {v:.2f} V)")
            return
        self.crawler.trot(half_cycles=half_cycles, stride=30)

    # ── camera: only send a frame when the question is visual ────────

    VISUAL_HINTS = ("ves", "ve ", "ver", "mira", "miras", "viendo", "foto", "camara", "imagen",
                    "que hay", "quien esta", "quien es", "quienes", "frente", "delante", "enfrente",
                    "color", "observa", "fijate", "describe", "cuantas personas", "cuantos", "que tengo",
                    "que traigo", "que llevo", "reconoces", "alrededor")

    # "mira a la izquierda" etc. are movement commands, not visual questions
    LOOK_COMMANDS = ("mira a la izquierda", "mira a la derecha", "mira hacia la izquierda",
                     "mira hacia la derecha", "mira arriba", "mira abajo", "mira hacia arriba",
                     "mira hacia abajo", "mira al frente", "ve a la izquierda", "ve a la derecha")

    def _wants_image(self, text):
        t = " " + self._norm_text(text) + " "
        for cmd in self.LOOK_COMMANDS:
            t = t.replace(cmd, " ")
        return any(h in t for h in self.VISUAL_HINTS)

    def trigger_wake_word(self):
        one_breath = self._wake_utterance is not None and self.stt.is_waked()
        if one_breath:
            triggered, disable_image, message = self._one_breath_trigger()
        if not one_breath or not triggered:
            triggered, disable_image, message = super().trigger_wake_word()
        if triggered and message and not self._wants_image(message):
            disable_image = True
        return triggered, disable_image, message

    def _one_breath_trigger(self):
        vosk_text, self._wake_utterance = self._wake_utterance, None
        self.stt.stop_listening()
        self._report_battery()
        # the Vosk text found the wake word; the cloud transcript is the one worth answering
        audio = getattr(self.stt, "last_audio", None)
        message = (self.stt.cloud_transcribe(audio) if audio and hasattr(self.stt, "cloud_transcribe") else None)
        message = message or vosk_text
        if len(self._extra_words(message)) < 2:
            return False, False, ""   # it was only the wake word after all: ask and listen as usual
        print(f"heard: {message}")
        self.on_heard(message)
        return True, False, message

    # ── conversation mode (no wake word between turns) ───────────────

    def _is_end_phrase(self, text):
        t = self._norm_text(text)
        return any(p and p in t for p in self.end_phrases)

    def on_finish_a_round(self):
        try:
            self._follow_up()
        finally:
            self._end_conversation()

    def _follow_up(self):
        self._finish_round_motion()
        if not self.follow_up_seconds or not hasattr(self.stt, "follow_up_timeout"):
            return
        ignored = 0
        while self.running:
            print(f"(sigo escuchando {self.follow_up_seconds}s, sin palabra clave; di 'adiós' para terminar)")
            self.stt.follow_up_timeout = self.follow_up_seconds
            try:
                text = self.listen()
            finally:
                self.stt.follow_up_timeout = None
            if not text:
                print("(silencio: vuelvo a esperar la palabra clave)")
                return
            if self._is_end_phrase(text):
                if self.farewell:
                    self.tts.say(self.farewell)
                return
            self.on_heard(text)
            result = self.think(self.FOLLOW_UP_TAG + text, disable_image=not self._wants_image(text))
            response_text = self.parse_response(result)
            if self._ignored:
                ignored += 1
                print("(no era para mí)")
                if ignored >= self.MAX_IGNORED:
                    print("(vuelvo a esperar la palabra clave)")
                    return
                continue
            ignored = 0
            if response_text:
                self.before_say(response_text)
                self.tts.say(response_text)
            self._finish_round_motion()

    # ── action dispatch ──────────────────────────────────────────────

    def _action_handler(self):
        while self._action_running:
            try:
                action, count = self.action_queue.get(timeout=0.5)
                self._action_busy.set()
                try:
                    if action == 'stop':
                        self.crawler.do_action("sit", speed=50)
                    elif action in self.ACTION_MAP:
                        method_name, kwargs = self.ACTION_MAP[action]
                        if action in self.STEP_ACTIONS:
                            kwargs = {**kwargs, self.STEP_ACTIONS[action]: count}
                        if method_name.startswith("self:"):
                            getattr(self, method_name[5:])(**kwargs)
                        else:
                            getattr(self.crawler, method_name)(**kwargs)
                    else:
                        print(f"Unknown action: {action}")
                except Exception as e:
                    print(f"(acción {action!r} falló: {e})")
                finally:
                    self._action_busy.clear()
            except queue.Empty:
                continue

    def _wait_actions_done(self):
        # wait until the queue is empty AND the current action has finished
        while not self.action_queue.empty() or self._action_busy.is_set():
            time.sleep(0.05)
        time.sleep(0.1)
