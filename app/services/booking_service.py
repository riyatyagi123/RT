"""Core booking business logic.

Both the human-facing Flask routes (patient/doctor blueprints) and the AI
agent's tool executors call into these functions, so a booking made via the
chat widget behaves identically to one made through the UI.
"""

from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.extensions import db, socketio
from app.models import Appointment, AvailabilitySlot, DoctorAbsence, DoctorProfile, User

ACTIVE_STATUSES = ("pending", "confirmed")
DISPLAY_DAYS_AHEAD = 45
DEFAULT_SLOT_MINUTES = 30
MAX_ABSENCE_DAYS = 90


def _notify(doctor_id, patient_id):
    """Push a live-update signal to whoever's dashboard cares about this appointment."""
    socketio.emit("appointments_changed", {}, room=f"doctor_{doctor_id}")
    socketio.emit("appointments_changed", {}, room=f"patient_{patient_id}")


class BookingError(ValueError):
    """Raised for any booking rule violation (bad slot, double-book, etc.)."""


class AbsenceConflict(BookingError):
    """Blocking this time would clash with appointments that are still booked."""

    def __init__(self, appointments):
        self.appointments = appointments
        count = len(appointments)
        super().__init__(
            f"{count} booked appointment{'s' if count != 1 else ''} fall{'s' if count == 1 else ''} in this time."
        )


def list_doctors(specialty=None):
    query = DoctorProfile.query.join(User)
    if specialty:
        query = query.filter(DoctorProfile.specialty.ilike(f"%{specialty}%"))
    return query.order_by(User.name).all()


def get_doctor_by_user_id(doctor_user_id):
    return DoctorProfile.query.filter_by(user_id=doctor_user_id).first()


def get_available_slots(doctor_user_id, days_ahead=14):
    """Return a list of bookable datetimes for a doctor over the next N days."""
    profile = get_doctor_by_user_id(doctor_user_id)
    if profile is None:
        return []

    booked = {
        appt.slot_datetime
        for appt in Appointment.query.filter_by(doctor_id=doctor_user_id)
        .filter(Appointment.status.in_(ACTIVE_STATUSES))
        .all()
    }

    now = datetime.now()
    today = date.today()
    horizon = datetime.combine(today + timedelta(days=days_ahead), datetime.min.time())
    blocks = [
        (a.start_datetime, a.end_datetime)
        for a in DoctorAbsence.query.filter(
            DoctorAbsence.doctor_id == doctor_user_id,
            DoctorAbsence.end_datetime > now,
            DoctorAbsence.start_datetime < horizon,
        ).all()
    ]
    slots = []

    for offset in range(days_ahead):
        day = today + timedelta(days=offset)
        weekday = day.weekday()  # Monday=0 ... Sunday=6

        for window in profile.availability_slots:
            if window.day_of_week != weekday:
                continue

            current = datetime.combine(day, window.start_time)
            end = datetime.combine(day, window.end_time)
            step = timedelta(minutes=window.slot_minutes)

            while current < end:
                slot_end = current + step
                is_blocked = any(start < slot_end and current < stop for start, stop in blocks)
                if current > now and current not in booked and not is_blocked:
                    slots.append(current)
                current += step

    slots.sort()
    return slots


def _period_for(dt):
    if dt.hour < 12:
        return "morning"
    if dt.hour < 17:
        return "afternoon"
    return "evening"


def get_available_slots_by_date(doctor_user_id, days_ahead=DISPLAY_DAYS_AHEAD):
    """Group bookable slots by calendar date, then by morning/afternoon/evening.

    Returns {"YYYY-MM-DD": {"morning": [{"iso": ..., "label": "9:00 AM"}, ...],
                             "afternoon": [...], "evening": [...]}}
    ready to hand straight to the client-side calendar as JSON.
    """
    grouped = {}
    for slot in get_available_slots(doctor_user_id, days_ahead=days_ahead):
        date_key = slot.date().isoformat()
        day = grouped.setdefault(date_key, {"morning": [], "afternoon": [], "evening": []})
        day[_period_for(slot)].append(
            {"iso": slot.isoformat(), "label": slot.strftime("%I:%M %p").lstrip("0")}
        )
    return grouped


def book_appointment(patient_id, doctor_user_id, slot_datetime, notes=None):
    if isinstance(slot_datetime, str):
        slot_datetime = datetime.fromisoformat(slot_datetime)

    doctor = User.query.filter_by(id=doctor_user_id, role="doctor").first()
    if doctor is None:
        raise BookingError("That doctor does not exist.")

    if slot_datetime <= datetime.now():
        raise BookingError("You can't book a slot in the past.")

    available = get_available_slots(doctor_user_id, days_ahead=DISPLAY_DAYS_AHEAD)
    if slot_datetime not in available:
        raise BookingError("That slot is no longer available. Please pick another one.")

    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_user_id,
        slot_datetime=slot_datetime,
        status="confirmed",
        notes=notes,
    )
    db.session.add(appointment)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise BookingError("That slot was just booked by someone else. Please pick another one.")
    _notify(doctor_user_id, patient_id)
    return appointment


def list_appointments_for_user(user_id, role, include_past=True):
    if role == "patient":
        query = Appointment.query.filter_by(patient_id=user_id)
    elif role == "doctor":
        query = Appointment.query.filter_by(doctor_id=user_id)
    else:
        raise BookingError("Unsupported role for appointment listing.")

    if not include_past:
        query = query.filter(Appointment.slot_datetime >= datetime.now())

    return query.order_by(Appointment.slot_datetime.desc()).all()


def _get_owned_appointment(appointment_id, user_id, role):
    appointment = db.session.get(Appointment, appointment_id)
    if appointment is None:
        raise BookingError("Appointment not found.")

    owner_field = "patient_id" if role == "patient" else "doctor_id"
    if getattr(appointment, owner_field) != user_id and role != "admin":
        raise BookingError("You don't have permission to modify this appointment.")

    return appointment


def cancel_appointment(appointment_id, user_id, role):
    appointment = _get_owned_appointment(appointment_id, user_id, role)
    appointment.status = "cancelled"
    db.session.commit()
    _notify(appointment.doctor_id, appointment.patient_id)
    return appointment


def reschedule_appointment(appointment_id, new_slot_datetime, user_id, role):
    if isinstance(new_slot_datetime, str):
        new_slot_datetime = datetime.fromisoformat(new_slot_datetime)

    appointment = _get_owned_appointment(appointment_id, user_id, role)

    available = get_available_slots(appointment.doctor_id, days_ahead=DISPLAY_DAYS_AHEAD)
    if new_slot_datetime not in available:
        raise BookingError("That slot is no longer available. Please pick another one.")

    appointment.slot_datetime = new_slot_datetime
    appointment.status = "confirmed"
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise BookingError("That slot was just booked by someone else. Please pick another one.")
    _notify(appointment.doctor_id, appointment.patient_id)
    return appointment


# --------------------------------------------------------------------------- doctor time off


def _slot_minutes_at(profile, dt):
    """Length of the appointment slot that starts at `dt` (from the doctor's hours)."""
    for window in profile.availability_slots if profile else []:
        if window.day_of_week == dt.weekday() and window.start_time <= dt.time() < window.end_time:
            return window.slot_minutes
    return DEFAULT_SLOT_MINUTES


def _parse_dt(value, field):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise BookingError(f"'{value}' isn't a valid {field}.")


def conflicting_appointments(doctor_user_id, start, end):
    """Active appointments that overlap [start, end)."""
    profile = get_doctor_by_user_id(doctor_user_id)
    candidates = (
        Appointment.query.filter_by(doctor_id=doctor_user_id)
        .filter(Appointment.status.in_(ACTIVE_STATUSES))
        .filter(Appointment.slot_datetime < end)
        .filter(Appointment.slot_datetime >= start - timedelta(hours=4))
        .order_by(Appointment.slot_datetime)
        .all()
    )
    return [
        a
        for a in candidates
        if a.slot_datetime + timedelta(minutes=_slot_minutes_at(profile, a.slot_datetime)) > start
    ]


def create_absence(doctor_user_id, start, end, reason=None, cancel_conflicts=False):
    """Block [start, end) on a doctor's calendar.

    If booked appointments fall inside the block, raises AbsenceConflict
    (listing them) unless `cancel_conflicts` is set, in which case they are
    cancelled and each patient's page updates live.
    """
    start = _parse_dt(start, "start time")
    end = _parse_dt(end, "end time")
    if end <= start:
        raise BookingError("The end time must be after the start time.")
    if end <= datetime.now():
        raise BookingError("You can't block time that is already in the past.")
    if end - start > timedelta(days=MAX_ABSENCE_DAYS):
        raise BookingError(f"A single block can be at most {MAX_ABSENCE_DAYS} days long.")
    reason = (reason or "").strip()[:200] or None

    conflicts = conflicting_appointments(doctor_user_id, start, end)
    if conflicts and not cancel_conflicts:
        raise AbsenceConflict(conflicts)

    absence = DoctorAbsence(doctor_id=doctor_user_id, start_datetime=start, end_datetime=end, reason=reason)
    db.session.add(absence)
    for appt in conflicts:
        appt.status = "cancelled"
    db.session.commit()

    patients = {a.patient_id for a in conflicts}
    for patient_id in patients:
        _notify(doctor_user_id, patient_id)
    if not patients:
        socketio.emit("appointments_changed", {}, room=f"doctor_{doctor_user_id}")
    return absence, conflicts


def delete_absence(absence_id, doctor_user_id):
    absence = db.session.get(DoctorAbsence, absence_id)
    if absence is None or absence.doctor_id != doctor_user_id:
        raise BookingError("That blocked time wasn't found.")
    db.session.delete(absence)
    db.session.commit()
    socketio.emit("appointments_changed", {}, room=f"doctor_{doctor_user_id}")


def calendar_events(doctor_user_id, start_day, days=7):
    """Everything the doctor's week calendar needs for [start_day, start_day + days)."""
    profile = get_doctor_by_user_id(doctor_user_id)
    range_start = datetime.combine(start_day, datetime.min.time())
    range_end = range_start + timedelta(days=days)

    appointments = (
        Appointment.query.filter_by(doctor_id=doctor_user_id)
        .filter(Appointment.status != "cancelled")
        .filter(Appointment.slot_datetime >= range_start, Appointment.slot_datetime < range_end)
        .order_by(Appointment.slot_datetime)
        .all()
    )
    absences = (
        DoctorAbsence.query.filter(
            DoctorAbsence.doctor_id == doctor_user_id,
            DoctorAbsence.start_datetime < range_end,
            DoctorAbsence.end_datetime > range_start,
        )
        .order_by(DoctorAbsence.start_datetime)
        .all()
    )

    def iso(dt):
        return dt.strftime("%Y-%m-%dT%H:%M")

    return {
        "range": {"start": range_start.date().isoformat(), "end": range_end.date().isoformat()},
        "now": iso(datetime.now()),
        "working_hours": [
            {
                "day_of_week": w.day_of_week,
                "start": w.start_time.strftime("%H:%M"),
                "end": w.end_time.strftime("%H:%M"),
                "slot_minutes": w.slot_minutes,
            }
            for w in (profile.availability_slots if profile else [])
        ],
        "appointments": [
            {
                "id": a.id,
                "start": iso(a.slot_datetime),
                "end": iso(a.slot_datetime + timedelta(minutes=_slot_minutes_at(profile, a.slot_datetime))),
                "patient_name": a.patient.name,
                "patient_email": a.patient.email,
                "status": a.status,
                "notes": a.notes,
                "booked_on": a.created_at.strftime("%d %b %Y") if a.created_at else None,
                "can_cancel": a.status in ACTIVE_STATUSES and a.slot_datetime > datetime.now(),
            }
            for a in appointments
        ],
        "absences": [
            {"id": b.id, "start": iso(b.start_datetime), "end": iso(b.end_datetime), "reason": b.reason}
            for b in absences
        ],
    }
