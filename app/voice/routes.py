"""Voice Assistant: talk to the booking agent out loud in the browser.

The page itself does the audio: the browser's Web Speech API turns speech
into text and reads replies aloud. Each utterance is sent to the normal
/ai_agent/chat endpoint with channel="voice", so the voice assistant uses
exactly the same agent, tools and security rules as the text chat.
"""

from flask import render_template
from flask_login import login_required

from app.utils import role_required
from app.voice import bp


@bp.route("/", methods=["GET"])
@login_required
@role_required("patient", "doctor")
def voice_assistant():
    return render_template("voice/assistant.html")
