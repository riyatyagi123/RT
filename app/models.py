from datetime import datetime, UTC

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

ROLES = ("patient", "doctor", "admin")


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))

    doctor_profile = db.relationship(
        "DoctorProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


class DoctorProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    specialty = db.Column(db.String(120), nullable=False, default="General Practice")
    bio = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(500), nullable=True)
    years_experience = db.Column(db.Integer, nullable=True)
    clinic_city = db.Column(db.String(120), nullable=True)

    user = db.relationship("User", back_populates="doctor_profile")
    availability_slots = db.relationship(
        "AvailabilitySlot", back_populates="doctor_profile", cascade="all, delete-orphan"
    )


class AvailabilitySlot(db.Model):
    """A recurring weekly availability window for a doctor."""

    id = db.Column(db.Integer, primary_key=True)
    doctor_profile_id = db.Column(db.Integer, db.ForeignKey("doctor_profile.id"), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday ... 6=Sunday
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    slot_minutes = db.Column(db.Integer, nullable=False, default=30)

    doctor_profile = db.relationship("DoctorProfile", back_populates="availability_slots")


class Appointment(db.Model):
    STATUSES = ("pending", "confirmed", "cancelled", "completed")

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    slot_datetime = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="confirmed")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))

    patient = db.relationship("User", foreign_keys=[patient_id])
    doctor = db.relationship("User", foreign_keys=[doctor_id])

    __table_args__ = (
        # Prevents two active appointments landing on the same doctor+slot even
        # under concurrent requests (e.g. a human and the AI agent booking at
        # the same instant) — cancelled/completed appointments don't block the
        # slot from being reused.
        db.Index(
            "uq_active_appointment_slot",
            "doctor_id",
            "slot_datetime",
            unique=True,
            sqlite_where=db.text("status IN ('pending', 'confirmed')"),
        ),
    )


class DoctorAbsence(db.Model):
    """A block of time a doctor is unavailable (leave, a conference, a break...).

    Any slot overlapping a block disappears from booking — for patients, for
    the AI agent, and for rescheduling — because get_available_slots() skips it.
    """

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))

    doctor = db.relationship("User")


class ChatMessage(db.Model):
    """One turn of a user's AI agent conversation, stored server-side.

    `content` holds JSON-encoded Anthropic message content (a plain string
    for user turns, or a list of content blocks for assistant/tool-result
    turns) — kept in the DB rather than the session cookie since tool-use
    exchanges get too large for a signed cookie.
    """

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))
