from datetime import date, datetime, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.doctor import bp
from app.services import booking_service
from app.utils import role_required


@bp.route("/dashboard")
@login_required
@role_required("doctor")
def dashboard():
    appointments = booking_service.list_appointments_for_user(
        current_user.id, "doctor", include_past=False
    )
    return render_template("dashboard.html", appointments=appointments)


@bp.route("/appointments/partial")
@login_required
@role_required("doctor")
def appointments_partial():
    appointments = booking_service.list_appointments_for_user(
        current_user.id, "doctor", include_past=False
    )
    return render_template("partials/doctor_appointments.html", appointments=appointments)


@bp.route("/appointments/<int:appointment_id>/cancel", methods=["POST"])
@login_required
@role_required("doctor")
def cancel(appointment_id):
    try:
        booking_service.cancel_appointment(appointment_id, current_user.id, "doctor")
        flash("Appointment cancelled.", "info")
    except booking_service.BookingError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("doctor.dashboard"))


# --------------------------------------------------------------------------- calendar (JSON)


def _appointment_summary(appt):
    return {
        "id": appt.id,
        "patient_name": appt.patient.name,
        "when": appt.slot_datetime.strftime("%a %d %b, %I:%M %p").replace(" 0", " "),
    }


@bp.route("/calendar/events")
@login_required
@role_required("doctor")
def calendar_events():
    """Appointments, blocked time and working hours for one week of the calendar."""
    try:
        start = date.fromisoformat(request.args.get("start", ""))
    except ValueError:
        today = date.today()
        start = today - timedelta(days=today.weekday())
    days = max(1, min(request.args.get("days", 7, type=int), 31))
    return jsonify(booking_service.calendar_events(current_user.id, start, days))


@bp.route("/absences", methods=["POST"])
@login_required
@role_required("doctor")
def create_absence():
    payload = request.get_json(silent=True) or {}
    try:
        absence, cancelled = booking_service.create_absence(
            current_user.id,
            payload.get("start"),
            payload.get("end"),
            reason=payload.get("reason"),
            cancel_conflicts=bool(payload.get("cancel_conflicts")),
        )
    except booking_service.AbsenceConflict as exc:
        return jsonify({
            "error": str(exc),
            "conflicts": [_appointment_summary(a) for a in exc.appointments],
        }), 409
    except booking_service.BookingError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "id": absence.id,
        "cancelled": [_appointment_summary(a) for a in cancelled],
    }), 201


@bp.route("/absences/<int:absence_id>", methods=["DELETE"])
@login_required
@role_required("doctor")
def delete_absence(absence_id):
    try:
        booking_service.delete_absence(absence_id, current_user.id)
    except booking_service.BookingError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"deleted": True})


@bp.route("/calendar/appointments/<int:appointment_id>/cancel", methods=["POST"])
@login_required
@role_required("doctor")
def cancel_from_calendar(appointment_id):
    try:
        booking_service.cancel_appointment(appointment_id, current_user.id, "doctor")
    except booking_service.BookingError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"cancelled": True})
