"""Manual tool-use loop for the booking agent, backed by Groq.

Kept deliberately simple and defensive: every external failure mode (missing
API key, network/API error, a tool raising, the model looping) has an
explicit, bounded fallback so a chat request can never hang or 500 — the
widget always gets back a plain-text reply.
"""

import json
import logging
import re
import time
from datetime import datetime

from groq import Groq, RateLimitError

from app.ai_agent.tools import execute_tool, schemas_for_role
from app.services.booking_service import BookingError

logger = logging.getLogger(__name__)

MODEL = "openai/gpt-oss-20b"
MAX_TOKENS = 600
MAX_TOOL_ROUNDS = 6
MAX_GENERATION_ATTEMPTS = 2
RATE_LIMIT_MAX_WAIT = 6.0
REQUEST_TIMEOUT = 20.0  # bound worst-case wait on Groq-side queueing; fail fast instead of hanging

# gpt-oss on Groq occasionally has a generation glitch where the model gets
# stuck rambling/repeating before recovering and self-correcting — the result
# is unreadable garbage (sometimes invisible characters, sometimes literal
# junk like repeated "Oops..." lines) prepended to an otherwise fine reply.
# This is a model-serving artifact, not something a prompt change fixes
# reliably, so we detect it and either salvage the model's own recovered
# answer (fast, no extra API call) or retry as a last resort.
_INVISIBLE_CHARS = ("​", "‌", "‍", "﻿")  # ZWSP, ZWNJ, ZWJ, BOM
_REPEATED_RUN = re.compile(r"(.{1,6})\1{6,}")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")  # normal replies never do this; garbled ones do
_SELF_CORRECTION_MARKER = re.compile(
    r"\b(?:oops|apologi[sz]e[sd]?|garbled|let me (?:correct|try again))\b", re.IGNORECASE
)
_RECOVERY_CUE = re.compile(
    r"(?:let me (?:correct that|give you the correct \w+|try (?:that )?again)|here(?:'s| is) the correct)",
    re.IGNORECASE,
)
_RETRY_AFTER_SECONDS = re.compile(r"try again in ([\d.]+)s")


def _looks_degenerate(text):
    if not text or len(text) < 20:
        return False
    invisible_ratio = sum(1 for ch in text if ch in _INVISIBLE_CHARS) / len(text)
    if invisible_ratio > 0.15:
        return True
    if _REPEATED_RUN.search(text):
        return True
    if _EXCESS_BLANK_LINES.search(text):
        return True
    return len(_SELF_CORRECTION_MARKER.findall(text)) >= 2


def _extract_recovery(text):
    """If the model rambled/glitched then self-corrected within the same
    response, pull out just the part after its last "let me correct that"
    style cue — recovering its own good answer without paying for another
    full API call (which is exactly the latency this is meant to avoid)."""
    matches = list(_RECOVERY_CUE.finditer(text))
    if not matches:
        return None
    tail = text[matches[-1].end():].lstrip(" :.\n\t-–—")
    if tail and not _looks_degenerate(tail):
        return tail
    return None


def _rate_limit_wait_seconds(exc, default=2.0):
    try:
        header_val = exc.response.headers.get("retry-after")
        if header_val:
            return min(float(header_val), RATE_LIMIT_MAX_WAIT)
    except Exception:
        pass
    match = _RETRY_AFTER_SECONDS.search(str(exc))
    if match:
        try:
            return min(float(match.group(1)), RATE_LIMIT_MAX_WAIT)
        except ValueError:
            pass
    return default


ROLE_CAPABILITIES = {
    "patient": "As a patient, they can ask you to list doctors (all, or by specialty or name), check a "
    "doctor's availability, and book, cancel or reschedule their own appointments.",
    "doctor": "As a doctor, they can ask you to list doctors (all, or by specialty or name, e.g. for a "
    "referral), check a doctor's availability, and view, cancel or reschedule their own appointments. "
    "Doctors can't book appointments through you; if asked, say that patients book for themselves.",
}

SYSTEM_PROMPT_TEMPLATE = """You are Svastha's booking assistant, embedded in a healthcare \
appointment app. You're talking to {name}, logged in as a {role}.
Current date/time: {now}.
{capabilities}

You can only act by calling the tools provided. You have no other way to affect the platform. Always call a tool \
to get real information rather than guessing, and never tell the user something was booked, \
cancelled, or rescheduled unless a tool call actually confirmed it. When you report appointment \
details back (time, doctor, status), use exactly what the tool returned — don't paraphrase \
times or invent details.

If a request is ambiguous (e.g. more than one doctor matches a name), ask a clarifying question \
instead of guessing. Keep replies short and conversational.

When the user asks for the list of doctors, or for doctors of a specialty (e.g. "dermatologist"), \
call list_doctors (with no query for everyone, or with the specialty) and give them the names. \
Never say you can't list doctors.

Each tool call is a slow network round trip, so avoid unnecessary ones. get_doctor_availability \
and book_appointment already accept a doctor's name directly and resolve it themselves — do NOT \
call list_doctors first just to look up an id when the user already named a specific doctor; \
only use list_doctors when the user is browsing by specialty or their doctor reference is \
genuinely ambiguous.

When the user asks about availability on a specific day — today, tomorrow, or a named date — \
compute that exact calendar date from "Current date/time" above and pass it as \
get_doctor_availability's `date` argument. Do not use `days_ahead` to approximate a single day; \
only use `days_ahead` for open-ended "what do you have soon" style requests.

This chat widget only displays plain text — it does not render markdown. Never use **bold**, \
_italics_, headings, or any other markdown syntax; asterisks and underscores will show up \
literally and look broken. Write plain sentences, and for lists just put each item on its own \
line starting with a hyphen.

The app also has real pages for this information (a doctor's profile, the browse-doctors list, \
the appointments page) that update automatically right after you call a tool — not from your \
text reply. So whenever the user asks you to show, display, view, or "put on screen" a doctor, \
their availability, or their appointments, call the relevant tool again (list_doctors, \
get_doctor_availability, or list_my_appointments) even if you already told them the answer \
earlier in the conversation — the fresh tool call is what makes the app display it for them."""


# Appended to the system prompt for spoken conversations (the browser Voice
# Assistant). The user *hears* the reply through
# text-to-speech, so it has to sound right when spoken, not look right on screen.
VOICE_PROMPT_ADDENDUM = """

IMPORTANT — this is a SPOKEN voice conversation (the app's Voice Assistant), not the \
text chat. Your reply will be read aloud by text-to-speech and the user is listening, not reading. So:
- Answer in one to three short spoken sentences. No lists, no hyphens, no symbols, no URLs, no ids.
- When there are several options, mention at most three, then ask which one they want.
- Say dates and times the way a person would ("Monday the 9th at 10:30 in the morning").
- Before booking, cancelling or rescheduling, read the details back and get a clear "yes" first.
- Ignore the earlier note about the app's pages updating; don't tell the user to look at a page.
- If the user says they are done, wish them well and say goodbye."""


def _client(app):
    api_key = app.config.get("GROQ_API_KEY")
    if not api_key or api_key == "your-groq-api-key-here":
        raise RuntimeError("GROQ_API_KEY is not configured.")
    return Groq(api_key=api_key)


def _to_function_tools(schemas):
    """Convert our provider-agnostic tool schemas to Groq/OpenAI's function-tool shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        }
        for s in schemas
    ]


def run_agent_turn(app, current_user, history, user_message, channel="web"):
    """Run one full user-turn of the tool-use loop.

    `history` is a list of OpenAI-style {"role", "content", ...} message dicts
    loaded from prior turns (no system message included). Returns
    (reply_text, new_messages) where new_messages is everything generated
    this turn (the user message, any assistant tool-call / tool-result
    exchanges, and the final assistant reply) — the caller persists each
    entry as one ChatMessage row.

    `channel` is "web" for the chat widget or "voice" for the browser
    Voice Assistant; voice
    adds spoken-style instructions to the system prompt. The tools, and the
    identity rules behind them, are exactly the same on both channels.
    """
    client = _client(app)

    messages = list(history)
    messages.append({"role": "user", "content": user_message})
    turn_start = len(messages) - 1

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        name=current_user.name,
        role=current_user.role,
        now=datetime.now().strftime("%A, %B %d, %Y %I:%M %p"),
        capabilities=ROLE_CAPABILITIES.get(current_user.role, ""),
    )
    if channel == "voice":
        system_prompt += VOICE_PROMPT_ADDENDUM
    tools = _to_function_tools(schemas_for_role(current_user.role))
    api_messages = [{"role": "system", "content": system_prompt}] + messages

    for _ in range(MAX_TOOL_ROUNDS):
        message = None
        reply = None
        for attempt in range(MAX_GENERATION_ATTEMPTS):
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    messages=api_messages,
                    tools=tools,
                    tool_choice="auto",
                    # Llama-family tool-calling on Groq sometimes emits stringified
                    # booleans/numbers (e.g. "false" instead of false) that fail
                    # Groq's strict server-side schema check. We coerce types
                    # ourselves in tools.py, so relax that check here instead of
                    # having the whole turn fail with a 400 over a formatting quirk.
                    disable_tool_validation=True,
                    # Groq's free/on-demand tier occasionally queues a request for
                    # a long time under load with no error — bound that instead of
                    # leaving the user staring at "Thinking..." indefinitely.
                    timeout=REQUEST_TIMEOUT,
                )
            except RateLimitError as exc:
                wait = _rate_limit_wait_seconds(exc)
                logger.warning("Groq rate limit hit (attempt %d): %s — waiting %.1fs", attempt + 1, exc, wait)
                if attempt + 1 >= MAX_GENERATION_ATTEMPTS:
                    return (
                        "The AI assistant is getting a lot of requests right now — please wait a few seconds and try again.",
                        [],
                    )
                time.sleep(wait)
                continue
            except Exception:
                logger.exception("Groq API call failed")
                return (
                    "I'm having trouble reaching the assistant right now — please try again in a moment.",
                    [],
                )

            message = response.choices[0].message
            if message.tool_calls:
                break  # tool calls are structured JSON, not prone to this text glitch

            candidate = (message.content or "").strip()
            if not _looks_degenerate(candidate):
                reply = candidate or "Done."
                break

            recovered = _extract_recovery(candidate)
            if recovered:
                # The model glitched then corrected itself in the same reply —
                # use its own recovered answer instead of paying for another
                # full API call (which is the exact latency this avoids).
                logger.warning("Degenerate output salvaged via recovery cue (attempt %d)", attempt + 1)
                reply = recovered
                break

            logger.warning(
                "Degenerate model output on attempt %d, retrying: %r", attempt + 1, candidate[:200]
            )
        else:
            reply = "Sorry, I had trouble putting together a clear reply just now — could you try asking again?"

        assistant_entry = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ]
        else:
            # Persist the vetted reply, not the raw model output — if both
            # generation attempts came back degenerate, message.content is
            # still garbage even though `reply` was replaced with a safe
            # fallback. Future turns must not see that garbage in their history.
            assistant_entry["content"] = reply
        messages.append(assistant_entry)
        api_messages.append(assistant_entry)

        if not message.tool_calls:
            return reply, messages[turn_start:]

        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            try:
                result = execute_tool(current_user, tc.function.name, args)
                content = json.dumps(result)
            except BookingError as exc:
                content = json.dumps({"error": str(exc)})
            except Exception:
                logger.exception("Tool execution failed: %s", tc.function.name)
                content = json.dumps(
                    {"error": "Something went wrong completing that action. Please try again."}
                )

            tool_entry = {"role": "tool", "tool_call_id": tc.id, "content": content}
            messages.append(tool_entry)
            api_messages.append(tool_entry)

    # Loop cap hit — still persist whatever actions were taken this turn,
    # just fall back to a generic reply since the model never wrapped up.
    return (
        "That's taking more steps than expected — could you rephrase or simplify your request?",
        messages[turn_start:],
    )
