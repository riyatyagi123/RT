from datetime import time

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth import bp
from app.auth.forms import LoginForm, RegistrationForm
from app.extensions import db
from app.models import AvailabilitySlot, ChatMessage, DoctorProfile, User
from app.seed import DEMO_PASSWORD


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    locked_role = request.args.get("role")
    if locked_role not in ("patient", "doctor"):
        locked_role = None

    if request.method == "GET" and locked_role:
        form = RegistrationForm(role=locked_role)
    else:
        form = RegistrationForm()

    if form.validate_on_submit():
        existing = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if existing:
            flash("An account with that email already exists.", "danger")
            return render_template("register.html", form=form, locked_role=locked_role)

        user = User(
            email=form.email.data.lower().strip(),
            name=form.name.data.strip(),
            role=form.role.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()  # get user.id before commit

        if user.role == "doctor":
            profile = DoctorProfile(
                user_id=user.id,
                specialty=form.specialty.data.strip() if form.specialty.data else "General Practice",
                bio=form.bio.data.strip() if form.bio.data else None,
            )
            db.session.add(profile)
            db.session.flush()

            # Default availability: Mon-Fri, 9am-5pm, 30-minute slots, so new
            # doctors have bookable slots right away.
            for day in range(0, 5):
                db.session.add(
                    AvailabilitySlot(
                        doctor_profile_id=profile.id,
                        day_of_week=day,
                        start_time=time(9, 0),
                        end_time=time(17, 0),
                        slot_minutes=30,
                    )
                )

        db.session.commit()
        login_user(user)
        flash(f"Welcome, {user.name}!", "success")
        return redirect(url_for("main.index"))

    return render_template("register.html", form=form, locked_role=locked_role)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    locked_role = request.args.get("role")
    if locked_role not in ("patient", "doctor"):
        locked_role = None

    show_quick_login = locked_role != "patient"

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user is None or not user.check_password(form.password.data):
            flash("Invalid email or password.", "danger")
            return render_template(
                "login.html",
                form=form,
                locked_role=locked_role,
                quick_login_doctors=_quick_login_doctors() if show_quick_login else [],
            )

        login_user(user)
        flash(f"Welcome back, {user.name}!", "success")
        return redirect(url_for("main.index"))

    return render_template(
        "login.html",
        form=form,
        locked_role=locked_role,
        quick_login_doctors=_quick_login_doctors() if show_quick_login else [],
    )


def _quick_login_doctors():
    """Doctor picker for the login page: pick a name, we fill in the login
    email for you. Password is also auto-filled for seeded demo accounts."""
    if not current_app.config.get("DEMO_MODE"):
        return []

    doctors = User.query.filter_by(role="doctor").order_by(User.name).all()
    return [
        {
            "name": doc.name,
            "email": doc.email,
            "demo_password": DEMO_PASSWORD if doc.email.endswith("@svastha.demo") else None,
        }
        for doc in doctors
    ]


@bp.route("/logout")
@login_required
def logout():
    # The AI chat widget's transcript belongs to this login session, not the
    # account long-term — clear it so the next person to log in on this
    # device (even the same user) starts with a clean assistant.
    ChatMessage.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()

    logout_user()
    flash("You've been logged out.", "info")
    return redirect(url_for("main.index"))
