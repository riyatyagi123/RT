from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO()
csrf = CSRFProtect()

login_manager.login_view = "auth.login"
login_manager.login_message_category = "info"
