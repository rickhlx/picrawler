"""Wake-word matching over a speech transcript.

Kept out of ``voice_active_crawler`` (and free of ``robot_hat``) so the text
rules can be read and tested on their own.  Two jobs:

- ``matches``: did the wake word turn up anywhere in what was heard?  The small
  Vosk models garble short phrases, so the match is accent-insensitive, ignores
  where in the sentence the word fell, and accepts the near-misses in
  ``WAKE_ALIASES``.
- ``has_question``: was there a real sentence around it ("compa, ¿qué hora
  es?") rather than just the wake word on its own ("oye, compa")?
"""
import re
import unicodedata

# What the small Spanish Vosk model tends to hear for each wake word.
WAKE_ALIASES = {
    "compa": ("compa", "compra", "comprar", "compacta", "compadre", "con pa", "com"),
}

# Vocatives around the wake word: they are how you call him, not what you asked.
INTERJECTIONS = ("oye", "oiga", "hey", "ey", "eh", "ay", "hola", "mira")

# A sentence has to clear both to count as a question asked in the same breath;
# below this it is noise the Vosk model tacked onto the wake word.
MIN_QUESTION_WORDS = 2
MIN_QUESTION_CHARS = 8

_PUNCT = re.compile(r"[^\w\s]+")


def norm_text(t):
    """Lowercase, strip accents, collapse whitespace."""
    t = unicodedata.normalize("NFD", (t or "").lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


def _patterns(wake, aliases):
    wake = norm_text(wake)
    yield wake
    for a in aliases.get(wake, ()):
        yield norm_text(a)


def _span(pat, heard):
    """(start, end) of `pat` in `heard`, or None.

    Short patterns need word boundaries; longer ones are matched anywhere, so a
    garbled ending ("compadre", "compacta") still counts.
    """
    if len(pat) >= 5:
        i = heard.find(pat)
        return (i, i + len(pat)) if i >= 0 else None
    m = re.search(r"\b" + re.escape(pat) + r"\b", heard)
    return m.span() if m else None


def find(heard, wake_words, aliases=WAKE_ALIASES):
    """Span of the wake phrase inside the transcript, or None if it is absent."""
    heard = norm_text(heard)
    for w in wake_words or ():
        for pat in _patterns(w, aliases):
            span = _span(pat, heard)
            if span:
                return span
    return None


def matches(heard, wake_words, aliases=WAKE_ALIASES):
    """True if a wake word was heard, wherever it fell in the sentence."""
    return find(heard, wake_words, aliases) is not None


def remainder(heard, wake_words, aliases=WAKE_ALIASES):
    """What was said around the wake word, minus the wake word and vocatives."""
    span = find(heard, wake_words, aliases)
    if span is None:
        return ""
    heard = norm_text(heard)
    rest = _PUNCT.sub(" ", heard[:span[0]] + " " + heard[span[1]:]).split()
    return " ".join(w for w in rest if w not in INTERJECTIONS)


def has_question(heard, wake_words, aliases=WAKE_ALIASES):
    """True if the wake word came wrapped in a sentence worth answering."""
    rest = remainder(heard, wake_words, aliases)
    return len(rest.split()) >= MIN_QUESTION_WORDS and len(rest) >= MIN_QUESTION_CHARS


def question_in(heard, wake_words, pcm=None, transcribe=None, aliases=WAKE_ALIASES):
    """The question said in the same breath as the wake word, or None to ask for it.

    `heard` is the offline transcript the wake word was spotted in; it decides
    whether there is a question at all, since it costs nothing.  The text itself
    is too garbled to answer, so the utterance's audio (`pcm`) goes to
    `transcribe` for a proper reading.  Anything missing or garbled and the
    caller falls back to listening for the question.
    """
    if not has_question(heard, wake_words, aliases):
        return None
    if not pcm or transcribe is None:
        return None
    text = (transcribe(pcm) or "").strip()
    # the cloud may hear only the wake word after all ("oye, compa")
    if not text or not has_question(text, wake_words, aliases):
        return None
    return text
