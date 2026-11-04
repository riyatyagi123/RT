from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user

from app.models import DoctorProfile

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.role == "doctor":
            return redirect(url_for("doctor.dashboard"))
        if current_user.role == "patient":
            return redirect(url_for("patient.browse_doctors"))

    doctors = DoctorProfile.query.join(DoctorProfile.user).order_by(DoctorProfile.id).all()
    specialties = sorted({d.specialty for d in doctors})

    return render_template(
        "landing.html",
        specialties=specialties[:8],
        all_doctors=doctors,
    )
