"""
Cloud voice for Petronilo (OpenAI), with offline fallbacks.

- ``PetroniloTTS``: OpenAI gpt-4o-mini-tts with a persona instruction so the
  voice sounds like a funny chilango (Mexico City) uncle.  If the request fails (no network,
  API error) it falls back to the offline Spanish Piper voice.
- ``HybridSTT``: keeps the small offline Vosk model for wake-word detection and
  end-of-utterance detection, but transcribes each utterance with OpenAI
  gpt-4o-transcribe, which handles Spanish (and names like "Petronilo") far
  better.  Falls back to the Vosk text if the cloud call fails.
"""
import io
import json
import os
import tempfile
import time
import wave

import requests
from robot_hat.tts import OpenAI_TTS, Piper
from sunfounder_voice_assistant._audio_player import AudioPlayer
from sunfounder_voice_assistant.stt import STT

from spanish_tts import PIPER_MODEL

TTS_VOICE = "echo"
TTS_GAIN = 2.5   # playback gain (library default 1.5); clipping-protected, lower if it distorts
TTS_INSTRUCTIONS = (
    "Habla con acento chilango de la Ciudad de México, bien marcado: la entonación cantadita que "
    "sube y alarga la última vocal al final de las frases (\"no manches, güeeey\", \"¿neta?\"), "
    "las eses bien pronunciadas y el ritmo de barrio defeño, pero sin hablar atropellado. Nada de acento neutro, norteño "
    "ni español de España. Eres Petronilo, el tío chistoso de la familia: relajado, burlón con cariño, "
    "con ritmo de cuentachistes, entonación expresiva y una risita ocasional. Nunca suenes como "
    "locutor ni como asistente corporativo."
)

STT_MODEL = "gpt-4o-transcribe"
STT_PROMPT = "Petronilo, robot araña, tío, mijo, órale, no manches."
STT_TIMEOUT = 15
STT_MAX_SECONDS = 30


class PetroniloTTS(OpenAI_TTS):
    def __init__(self, api_key, voice=TTS_VOICE, instructions=TTS_INSTRUCTIONS, fallback=None,
                 gain=TTS_GAIN, **kwargs):
        super().__init__(api_key=api_key, voice=OpenAI_TTS.Voice(voice),
                         model=OpenAI_TTS.Model.GPT_4O_MINI_TTS, gain=gain, **kwargs)
        self.instructions = instructions
        self._fallback = fallback

    def _get_fallback(self):
        if self._fallback is None:
            self._fallback = Piper(model=PIPER_MODEL)
        return self._fallback

    def say(self, words, instructions=None, stream=True):
        """Speak one line.

        Note: `stream=True` on the library's OpenAI TTS writes the raw HTTP body
        (WAV header included) into a PCM stream opened at the wrong sample rate,
        which produces clicks/static and starves the DAC when network chunks are
        late. We always synthesize to a file and play that instead: play_file
        reads the header and uses the file's real sample rate.
        """
        if not words or not str(words).strip():
            return
        ok = False
        path = None
        try:
            fd, path = tempfile.mkstemp(prefix="petronilo_say_", suffix=f".{self.AUDIO_FORMAT}")
            os.close(fd)
            ok = self.tts(words, output_file=path,
                          instructions=instructions or self.instructions, stream=False)
            if ok:
                with AudioPlayer(gain=self._gain) as player:
                    player.play_file(path)
        except Exception as e:
            self.log.error(f"OpenAI TTS failed: {e}")
            ok = False
        finally:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        if not ok:
            print("(OpenAI TTS unavailable, using offline Piper voice)")
            self._get_fallback().say(words)


class HybridSTT(STT):
    def __init__(self, api_key, language="es", model=STT_MODEL, prompt=STT_PROMPT, **kwargs):
        super().__init__(language=language, **kwargs)
        self._api_key = api_key
        self._cloud_model = model
        self._cloud_prompt = prompt
        self._cloud_language = language.split("-")[0]
        self.last_source = None  # "cloud" or "vosk", for debugging
        # When set (seconds), listen() gives up and returns nothing if no speech
        # has started within that time. Used for the follow-up window.
        self.follow_up_timeout = None

    # ---- cloud transcription -------------------------------------------------
    def _pcm_to_wav(self, pcm):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self._samplerate)
            w.writeframes(pcm)
        return buf.getvalue()

    def cloud_transcribe(self, pcm):
        """Return the cloud transcript for raw int16 mono PCM, or None on failure."""
        try:
            wav = self._pcm_to_wav(pcm)
            t0 = time.time()
            r = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                files={"file": ("audio.wav", wav, "audio/wav")},
                data={"model": self._cloud_model, "language": self._cloud_language,
                      "prompt": self._cloud_prompt, "response_format": "json"},
                timeout=STT_TIMEOUT,
            )
            if r.status_code != 200:
                self.log.error(f"transcription HTTP {r.status_code}")  # body not logged: may echo the key
                return None
            text = (r.json().get("text") or "").strip()
            self.log.debug(f"cloud stt {time.time()-t0:.1f}s: {text}")
            return text or None
        except Exception as e:
            self.log.error(f"transcription failed: {e}")
            return None

    # ---- utterance listening (after wake) -----------------------------------
    def _listen_streaming(self, q, device=None, samplerate=None, callback=None):
        import queue as _queue
        import sounddevice as sd
        max_bytes = int(STT_MAX_SECONDS * self._samplerate * 2)
        audio = bytearray()
        t_start = time.time()
        speech_started = False
        with sd.RawInputStream(samplerate=samplerate, blocksize=1024, device=device,
                               dtype="int16", channels=1, callback=callback):
            while True:
                if self.stop_listening_event.is_set():
                    return None
                if (self.follow_up_timeout and not speech_started
                        and time.time() - t_start > self.follow_up_timeout):
                    return None
                try:
                    data = q.get(timeout=0.5)
                except _queue.Empty:
                    continue
                audio += data
                if len(audio) > max_bytes:
                    del audio[:len(audio) - max_bytes]
                result = {"done": False, "partial": "", "final": ""}
                if self.recognizer.AcceptWaveform(data):
                    text = json.loads(self.recognizer.Result())["text"].strip()
                    if text == "":
                        audio.clear()   # silence only: drop it, keep waiting
                        continue
                    cloud = self.cloud_transcribe(bytes(audio))
                    if cloud:
                        self.last_source = "cloud"
                        text = cloud
                    else:
                        self.last_source = "vosk"
                        print("(cloud transcription unavailable, using offline Vosk text)")
                    result["done"] = True
                    result["final"] = text
                    yield result
                    break
                else:
                    partial = json.loads(self.recognizer.PartialResult())["partial"]
                    if partial == "" or partial.isspace():
                        continue
                    if not speech_started:
                        speech_started = True
                        # Vosk's Spanish partials are mostly noise; show a plain indicator instead.
                        result["partial"] = "(escuchando...)"
                        yield result


# ---------------------------------------------------------------------------
# Sentence-streamed speech: speak while the LLM is still writing
# ---------------------------------------------------------------------------
import os
import queue
import re
import tempfile
import threading

from sunfounder_voice_assistant._audio_player import AudioPlayer

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_MIN_SENTENCE = 12   # merge very short fragments ("¡Órale!") with the next one


class SpeechPipeline:
    """Feed text chunks as they stream in; sentences are synthesized ahead of
    playback (network) and played in order, so speech starts after the first
    sentence instead of after the whole answer.  Uses PetroniloTTS (OpenAI)
    and falls back to its offline Piper voice per sentence."""

    def __init__(self, tts):
        self.tts = tts
        self._buf = ""
        self._pending = ""
        self._sentences = queue.Queue()   # str | None
        self._audio = queue.Queue()       # (path|None, sentence) | None
        self._done = threading.Event()
        self._cancelled = threading.Event()
        self._tmpdir = tempfile.mkdtemp(prefix="petronilo_")
        threading.Thread(target=self._synth_worker, daemon=True).start()
        threading.Thread(target=self._play_worker, daemon=True).start()

    # -- producer side --------------------------------------------------------
    def feed(self, chunk):
        if not chunk or self._cancelled.is_set():
            return
        self._buf += chunk
        parts = _SENTENCE_SPLIT.split(self._buf)
        self._buf = parts.pop() if parts else ""
        for p in parts:
            self._emit(p)

    def _emit(self, sentence):
        if self._cancelled.is_set():
            return
        s = (self._pending + " " + sentence).strip() if self._pending else sentence.strip()
        if not s:
            return
        if len(s) < _MIN_SENTENCE:
            self._pending = s
            return
        self._pending = ""
        self._sentences.put(s)

    def cancel(self):
        """Cancel this pipeline: drops everything not already playing. The
        sentence currently playing cannot be interrupted (AudioPlayer has no
        stop call), so speech trails off after that one sentence. Safe to
        call more than once or after finish()."""
        if self._cancelled.is_set():
            return
        self._cancelled.set()
        while True:
            try:
                self._sentences.get_nowait()
            except queue.Empty:
                break
        while True:
            try:
                item = self._audio.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                path, _sentence = item
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        # unblock the synth worker (it forwards this None to the play worker,
        # which is what sets _done and lets finish() return)
        self._sentences.put(None)

    def finish(self, timeout=120):
        """Flush the remainder and block until playback has finished. After
        cancel(), the pending text is dropped: this just waits for the
        already-cancelled pipeline to wind down."""
        if not self._cancelled.is_set():
            tail = (self._pending + " " + self._buf).strip()
            self._pending = self._buf = ""
            if tail:
                self._sentences.put(tail)
            self._sentences.put(None)
        self._done.wait(timeout)

    # -- workers --------------------------------------------------------------
    def _synth_worker(self):
        n = 0
        while True:
            s = self._sentences.get()
            if s is None:
                self._audio.put(None)
                break
            if self._cancelled.is_set():
                continue   # drop it, keep draining until the sentinel
            path = os.path.join(self._tmpdir, f"s{n}.wav")
            n += 1
            ok = False
            try:
                ok = self.tts.tts(s, output_file=path, instructions=self.tts.instructions, stream=False)
            except Exception as e:
                self.tts.log.error(f"OpenAI TTS failed: {e}")
            self._audio.put((path if ok else None, s))

    def _play_worker(self):
        try:
            while True:
                item = self._audio.get()
                if item is None:
                    break
                path, sentence = item
                try:
                    if path:
                        with AudioPlayer(gain=self.tts._gain) as player:
                            player.play_file(path)
                    else:
                        print("(OpenAI TTS unavailable, using offline Piper voice)")
                        self.tts._get_fallback().say(sentence)
                except Exception as e:
                    self.tts.log.error(f"playback failed: {e}")
                finally:
                    if path:
                        try:
                            os.remove(path)
                        except OSError:
                            pass
        finally:
            try:
                os.rmdir(self._tmpdir)
            except OSError:
                pass
            self._done.set()
