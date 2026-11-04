from flask import Blueprint

bp = Blueprint("voice", __name__)

from app.voice import routes  # noqa: E402,F401
