from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import User
from app.patient import bp
from app.services import booking_service
from app.utils import role_required


@bp.route("/doctors")
@login_required
@role_required("patient")
def browse_doctors():
    specialty = request.args.get("specialty", "").strip() or None
    doctors = booking_service.list_doctors(specialty=specialty)
    return render_template("browse.html", doctors=doctors, specialty=specialty or "")


@bp.route("/doctors/<int:doctor_user_id>")
@login_required
@role_required("patient")
def doctor_detail(doctor_user_id):
    doctor = User.query.filter_by(id=doctor_user_id, role="doctor").first_or_404()
    slots_by_date = booking_service.get_available_slots_by_date(doctor_user_id)
    return render_template("doctor_detail.html", doctor=doctor, slots_by_date=slots_by_date)


@bp.route("/book", methods=["POST"])
@login_required
@role_required("patient")
def book():
    doctor_user_id = request.form.get("doctor_id", type=int)
    slot_datetime = request.form.get("slot_datetime")
    notes = request.form.get("notes", "").strip() or None

    try:
        booking_service.book_appointment(current_user.id, doctor_user_id, slot_datetime, notes=notes)
        flash("Appointment booked!", "success")
    except booking_service.BookingError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("patient.doctor_detail", doctor_user_id=doctor_user_id))

    return redirect(url_for("patient.my_appointments"))


@bp.route("/appointments")
@login_required
@role_required("patient")
def my_appointments():
    appointments = booking_service.list_appointments_for_user(current_user.id, "patient")
    return render_template("my_appointments.html", appointments=appointments)


@bp.route("/appointments/partial")
@login_required
@role_required("patient")
def appointments_partial():
    appointments = booking_service.list_appointments_for_user(current_user.id, "patient")
    return render_template("partials/patient_appointments.html", appointments=appointments)


@bp.route("/appointments/<int:appointment_id>/cancel", methods=["POST"])
@login_required
@role_required("patient")
def cancel(appointment_id):
    try:
        booking_service.cancel_appointment(appointment_id, current_user.id, "patient")
        flash("Appointment cancelled.", "info")
    except booking_service.BookingError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("patient.my_appointments"))
