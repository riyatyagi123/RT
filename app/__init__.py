from datetime import datetime

from flask import Flask

from config import Config
from app.extensions import csrf, db, login_manager, socketio


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")
    csrf.init_app(app)

    from app import sockets  # noqa: F401 registers @socketio.on handlers

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")

    from app.patient import bp as patient_bp
    app.register_blueprint(patient_bp, url_prefix="/patient")

    from app.doctor import bp as doctor_bp
    app.register_blueprint(doctor_bp, url_prefix="/doctor")

    from app.ai_agent import bp as ai_agent_bp
    app.register_blueprint(ai_agent_bp, url_prefix="/ai_agent")

    from app.voice import bp as voice_bp
    app.register_blueprint(voice_bp, url_prefix="/voice")

    @app.context_processor
    def inject_globals():
        return {"now_year": datetime.now().year}

    with app.app_context():
        db.create_all()
        from app.seed import seed_demo_data
        seed_demo_data()

    return app
