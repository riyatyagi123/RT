import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///dr_appointment.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    # Shows a "quick login" doctor picker on the login page that autofills
    # credentials for seeded demo accounts. Turn off for a real deployment.
    DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"
