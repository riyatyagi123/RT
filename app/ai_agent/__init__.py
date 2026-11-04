from flask import Blueprint

bp = Blueprint("ai_agent", __name__)

from app.ai_agent import routes  # noqa: E402,F401
