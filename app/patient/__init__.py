from flask import Blueprint

bp = Blueprint("patient", __name__, template_folder="../templates/patient")

from app.patient import routes  # noqa: E402,F401
