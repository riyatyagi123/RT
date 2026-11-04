import re
from functools import wraps

from flask import abort
from flask_login import current_user


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


# --- Voice assistant helpers ----------------------------------------------

# Whole-utterance phrases that end the call. Matched against the full
# transcript (not a prefix), so "nothing is available?" won't hang up.
GOODBYE_PHRASES = {
    "bye", "goodbye", "bye bye", "thats all", "that is all", "nothing", "nothing else",
    "no thanks", "no thank you", "no thats all", "no nothing else", "im done", "thats it",
}


def is_goodbye(speech):
    words = re.sub(r"[^a-z ]", "", speech.lower().replace("-", " ")).split()
    phrase = " ".join(words)
    if phrase in GOODBYE_PHRASES:
        return True
    # "okay thank you bye", "thanks goodbye", "no thats all bye" ...
    return bool(words) and words[-1] in ("bye", "goodbye") and len(words) <= 6


def speakable(text):
    """Make agent output sound right through text-to-speech."""
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"[*_#`>|]", "", text)
    lines = [ln.strip().lstrip("-•").strip() for ln in text.splitlines()]
    sentences = []
    for ln in lines:
        if not ln:
            continue
        sentences.append(ln if ln[-1] in ".?!:" else ln + ".")
    spoken = " ".join(sentences)
    return re.sub(r"\s{2,}", " ", spoken).strip() or "Sorry, I didn't get that."
