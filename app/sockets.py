"""SocketIO room wiring: every logged-in patient/doctor joins a personal room
so booking_service can push live updates to exactly the people who need them.
"""

from flask_login import current_user
from flask_socketio import join_room

from app.extensions import socketio


@socketio.on("connect")
def handle_connect():
    if not current_user.is_authenticated:
        return
    if current_user.role == "doctor":
        join_room(f"doctor_{current_user.id}")
    elif current_user.role == "patient":
        join_room(f"patient_{current_user.id}")
