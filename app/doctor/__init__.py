from flask import Blueprint

bp = Blueprint("doctor", __name__, template_folder="../templates/doctor")

from app.doctor import routes  # noqa: E402,F401
