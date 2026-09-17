"""Spanish TTS helpers for the PiCrawler examples.

- PIPER_MODEL: Mexican Spanish Piper voice (downloaded on first use to
  ~/.piper_models).  Swap for "es_MX-claude-high" (better, slower) or an
  "es_ES-*" voice for Castilian Spanish.
- EspeakES: robot_hat\x27s Espeak wrapper has no language option, so this
  subclass passes the Latin American Spanish voice to espeak.
"""
from robot_hat.tts import Espeak

PIPER_MODEL = "es_MX-ald-medium"
ESPEAK_VOICE = "es-la"


class EspeakES(Espeak):
    """Espeak with a Spanish voice."""

    def __init__(self, *args, voice: str = ESPEAK_VOICE, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._voice = voice
        self._lang = "es-MX"

    def tts(self, words: str, file_path: str) -> None:
        from sunfounder_voice_assistant._utils import run_command
        cmd = (f"espeak -v {self._voice} -a{self._amp} -s{self._speed} "
               f"-g{self._gap} -p{self._pitch} \"{words}\" -w {file_path}")
        status, result = run_command(cmd)
        if status != 0:
            raise Exception(f"tts-espeak:\n\t{result}")
