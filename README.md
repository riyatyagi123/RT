# Svastha — Doctor Appointment Booking

Svastha is a full-stack doctor appointment booking platform built with Flask.
It supports three user roles (patient, doctor, admin), real-time appointment
sync across open browser tabs, and an AI chat assistant that can browse
doctors and book, reschedule, or cancel appointments conversationally on the
user's behalf.

## Features

- **Patient portal** — browse doctors by specialty or city, view a doctor's
  open slots on a calendar, and book, reschedule, or cancel appointments.
- **Doctor calendar** — a Teams-style week calendar on the doctor dashboard
  showing working hours, upcoming appointments and blocked time. Drag across
  empty time (or use "Block time") to block a few hours or whole days of
  leave; click an appointment to see the patient's details or cancel it.
  Blocked time disappears from booking for patients and the AI assistant.
- **Admin impersonation** — an admin can "View as" any patient or doctor
  account for support/debugging, with a persistent banner to return.
- **Real-time updates** — Flask-SocketIO pushes live updates to exactly the
  patient and doctor involved when an appointment is booked, confirmed,
  rescheduled, or cancelled, so two people can never double-book the same
  slot and dashboards never need a manual refresh.
- **AI booking assistant** — a persistent chat widget backed by an LLM
  (via the Groq API) that can look up doctors, check availability, and
  book/reschedule/cancel appointments through the same tool calls the UI
  uses — not just a FAQ bot, it takes real actions.

- **Voice assistant** — talk to the AI agent out loud in the browser, like a
  phone call: speech is recognised in the browser, the agent answers in short
  spoken replies, and bookings made by voice are real bookings.

## Tech Stack

| Layer          | Technology                                              |
|----------------|-----------------------------------------------------------|
| Backend        | Flask, Flask-Login, Flask-WTF (CSRF)                     |
| Database / ORM | SQLite via Flask-SQLAlchemy                              |
| Real-time      | Flask-SocketIO (WebSockets)                              |
| AI             | Groq API (`groq` Python SDK), manual tool-use loop        |
| Voice          | Web Speech API in the browser (speech recognition + speech synthesis) |
| Frontend       | Server-rendered Jinja templates, vanilla CSS/JS, htmx + Alpine.js (CDN, no build step) |

## Architecture Notes

All booking logic — listing doctors, computing open slots, booking,
rescheduling, cancelling — lives in one place: `app/services/booking_service.py`.
Both the Flask routes (what a human clicks through in the UI) and the AI
agent's tool executors (`app/ai_agent/tools.py`) call into these same
functions. This means a booking made through the chat widget produces
exactly the same database state, validation, and real-time notification as
one made through a form — the AI has no special/back-door path.

The AI agent itself (`app/ai_agent/groq_client.py`) runs a bounded tool-use
loop against the Groq API: it sends the conversation plus a set of
JSON-schema tool definitions, executes whichever tools the model calls,
feeds the results back, and repeats until the model produces a final reply.
Every external failure mode — a missing API key, a network error, a rate
limit, a tool raising, or the model looping — has an explicit fallback, so a
chat request can never hang or crash; the widget always gets back a plain
response.

## Project Structure

```
app/
  auth/           login, signup, logout
  patient/        doctor browsing, booking, patient dashboard
  doctor/         dashboard + week calendar, blocked time (JSON API)
  ai_agent/       chat endpoint, Groq client, and tool definitions
  voice/          Voice Assistant page (browser speech in/out)
  services/       booking_service.py — shared business logic
  models.py       User, DoctorProfile, AvailabilitySlot, DoctorAbsence,
                  Appointment, ChatMessage
  sockets.py      Flask-SocketIO room/event handlers
  seed.py         demo doctor data seeded on first run
  static/         CSS, JS, images
  templates/      Jinja templates (incl. htmx partials)
config.py         app configuration (reads from .env)
run.py            entry point (runs the app via SocketIO)
requirements.txt  Python dependencies
```

## Prerequisites

- Python 3.12+
- A [Groq API key](https://console.groq.com/) (free tier works) — only
  needed for the AI chat assistant; the rest of the app works without it.

## Setup

1. **Clone and enter the project**

   ```bash
   git clone <repo-url>
   cd dr_appointment
   ```

2. **Create and activate a virtual environment**

   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   Copy `.env.example` to `.env` and fill in the values:

   ```bash
   cp .env.example .env
   ```

   ```ini
   SECRET_KEY=change-this-to-a-random-secret-string
   DATABASE_URL=sqlite:///dr_appointment.db
   GROQ_API_KEY=your-groq-api-key-here
   ```

   | Variable       | Required | Notes                                                                 |
   |----------------|----------|------------------------------------------------------------------------|
   | `SECRET_KEY`   | Yes      | Any random string, used for sessions/CSRF.                            |
   | `DATABASE_URL` | No       | Defaults to a local SQLite file; no extra setup needed.               |
   | `GROQ_API_KEY` | For AI chat | The rest of the app runs fine without it — only the assistant is disabled. |
   | `DEMO_MODE`    | No       | Defaults to `true`. Shows a quick-login doctor picker on the login page for seeded demo accounts. Set to `false` for a real deployment. |

5. **Run the app**

   ```bash
   python run.py
   ```

   The database is created and seeded with demo doctors automatically on
   first run (SQLite file + ~12 demo doctor accounts, password
   `SvasthaDemo@2026`). The app is available at **http://127.0.0.1:5000**.

## Usage

- Sign up as a patient at `/auth/signup`, or use the `DEMO_MODE` quick-login
  picker on the login page to sign in as one of the seeded demo doctors.
- **As a patient**: browse doctors, view a doctor's availability on the
  calendar, and book a slot — or open the chat assistant and ask it to
  find/book a doctor for you directly.
- **As a doctor**: see your week on the dashboard calendar, drag across
  empty time to block it (or use "+ Block time" for leave), and click an
  appointment for the patient's details or to cancel it.

## Voice Assistant (browser)

Open **Voice Assistant** in the top menu and tap the microphone. It works in
Google Chrome and Microsoft Edge (desktop or Android) and needs no extra
setup, API keys or phone number. Browsers only allow the microphone on
`https://` sites or `localhost`.

How it works: the browser's Web Speech API turns the user's speech into text
and sends it to the existing `/ai_agent/chat` endpoint with
`"channel": "voice"`. The server runs the same agent and tools as the text
chat, with the spoken-style system prompt, and returns a TTS-ready `speech`
field, which the browser reads aloud before listening again. Saying "bye" or
"that's all" ends the call; long silences end it too.

## Notes

- The SQLite database file lives at `instance/dr_appointment.db` and is
  created automatically — delete it to reset all data (it will reseed on
  the next run).
- Demo doctor photos are placeholder portraits from randomuser.me, not real
  photos.
