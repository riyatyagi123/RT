import json
import logging

from flask import current_app, jsonify, request, url_for
from flask_login import current_user, login_required

from app.ai_agent import bp
from app.ai_agent.groq_client import run_agent_turn
from app.extensions import db
from app.models import ChatMessage
from app.utils import is_goodbye, role_required, speakable

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 2000
HISTORY_TURN_LIMIT = 4  # complete user<->assistant exchanges to keep, not raw rows
HISTORY_ROW_FETCH_CAP = 200  # generous upper bound just to keep the SQL query itself cheap

# Tools that changed or read appointment data — when the agent uses one of
# these, the corresponding real page (not just the chat bubble) should show
# the result, so the user sees it reflected on screen, not just described.
APPOINTMENT_TOOLS = {
    "list_my_appointments",
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
}


def _executed_tools(messages):
    """Pair each tool_call this turn with its result, in call order.

    Returns a list of {"name": str, "result": dict|None} — result is the
    parsed JSON a tool returned, so callers can pull real ids (e.g. which
    doctor) out of it rather than re-parsing the model's free text.
    """
    results_by_id = {m["tool_call_id"]: m.get("content") for m in messages if m.get("role") == "tool"}

    executed = []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            raw_result = results_by_id.get(tc.get("id"))
            try:
                result = json.loads(raw_result) if raw_result else None
            except (TypeError, ValueError):
                result = None
            executed.append({"name": tc.get("function", {}).get("name"), "result": result})
    return executed


def _redirect_target(role, new_messages):
    executed = _executed_tools(new_messages)
    names = {e["name"] for e in executed}

    if names & APPOINTMENT_TOOLS:
        if role == "patient":
            return url_for("patient.my_appointments")
        if role == "doctor":
            return url_for("doctor.dashboard")
        return None

    if role != "patient":
        return None  # doctor-browsing tools are patient-only

    # A specific doctor's availability was checked — that's the clearest
    # signal of which single doctor page to show.
    for e in reversed(executed):
        if e["name"] == "get_doctor_availability" and e["result"] and e["result"].get("doctor_id"):
            return url_for("patient.doctor_detail", doctor_user_id=e["result"]["doctor_id"])

    # Otherwise fall back to whatever list_doctors turned up: a single match
    # goes straight to that doctor's page, multiple matches go to the browse
    # page so the user can see them all on screen.
    for e in reversed(executed):
        if e["name"] == "list_doctors" and e["result"]:
            doctors = e["result"].get("doctors") or []
            if len(doctors) == 1:
                return url_for("patient.doctor_detail", doctor_user_id=doctors[0]["doctor_id"])
            if len(doctors) > 1:
                return url_for("patient.browse_doctors")

    return None


def _load_history(user_id, limit_turns=HISTORY_TURN_LIMIT):
    """Reconstruct the last `limit_turns` complete turns in OpenAI/Groq message format.

    Each ChatMessage row stores a full message dict (role, content, and —
    for assistant/tool turns — tool_calls/tool_call_id) as JSON, so it can be
    fed straight back to the API as conversation history.

    Truncating by raw row count (rather than by whole turns) can cut a turn
    in half — e.g. keeping a "tool" role row without the assistant
    "tool_calls" row that produced it. That's an invalid message sequence to
    hand back to the API, and it also makes the displayed transcript look
    like messages randomly vanished once the row cap is crossed. Grouping by
    turn (each starts at a "user" row) guarantees we only ever drop whole
    turns, never split one.
    """
    rows = (
        ChatMessage.query.filter_by(user_id=user_id)
        .order_by(ChatMessage.id.desc())
        .limit(HISTORY_ROW_FETCH_CAP)
        .all()
    )
    rows.reverse()

    turns = []
    current_turn = []
    for r in rows:
        parsed = json.loads(r.content)
        if parsed.get("role") == "user":
            if current_turn:
                turns.append(current_turn)
            current_turn = [parsed]
        else:
            current_turn.append(parsed)
    if current_turn:
        turns.append(current_turn)

    kept = turns[-limit_turns:]
    return [message for turn in kept for message in turn]


def _save_messages(user_id, messages):
    for m in messages:
        db.session.add(ChatMessage(user_id=user_id, role=m["role"], content=json.dumps(m)))
    db.session.commit()


@bp.route("/chat", methods=["POST"])
@login_required
@role_required("patient", "doctor")
def chat():
    payload = request.get_json(silent=True) or {}
    user_message = (payload.get("message") or "").strip()
    # "voice" = the browser voice assistant: same agent and tools, but replies
    # are written to be spoken, and the response carries a TTS-ready version.
    channel = "voice" if payload.get("channel") == "voice" else "web"

    if not user_message:
        return jsonify({"error": "Message can't be empty."}), 400
    if len(user_message) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": f"Message is too long (max {MAX_MESSAGE_LENGTH} characters)."}), 400

    if channel == "voice" and is_goodbye(user_message):
        bye = "Thank you for talking to Svastha. Take care, goodbye!"
        return jsonify({"reply": bye, "speech": bye, "end_call": True})

    try:
        history = _load_history(current_user.id)
        reply, new_messages = run_agent_turn(
            current_app._get_current_object(), current_user, history, user_message, channel=channel
        )
        if new_messages:
            _save_messages(current_user.id, new_messages)
        if channel == "voice":
            # No page redirects mid-conversation: navigating away would cut the
            # voice session off. Pages still update live through SocketIO.
            return jsonify({"reply": reply, "speech": speakable(reply), "end_call": False})
        redirect_url = _redirect_target(current_user.role, new_messages)
        return jsonify({"reply": reply, "redirect": redirect_url})
    except RuntimeError as exc:
        # Missing/placeholder GROQ_API_KEY — a config issue, not a user error.
        logger.warning("AI agent unavailable: %s", exc)
        msg = "The AI assistant isn't set up yet — an API key still needs to be added."
        return jsonify({"reply": msg, "speech": speakable(msg)})
    except Exception:
        logger.exception("Unhandled error in AI agent chat")
        msg = "Something went wrong on my end — please try again."
        return jsonify({"reply": msg, "speech": speakable(msg)})


@bp.route("/history", methods=["GET"])
@login_required
@role_required("patient", "doctor")
def history():
    """Chat transcript for redrawing the widget on page load (text turns only)."""
    rows = _load_history(current_user.id)
    turns = []
    for m in rows:
        if m["role"] == "user" and m.get("content"):
            turns.append({"role": "user", "text": m["content"]})
        elif m["role"] == "assistant" and m.get("content"):
            turns.append({"role": "assistant", "text": m["content"]})
    return jsonify({"turns": turns})
