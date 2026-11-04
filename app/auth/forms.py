from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional


class RegistrationForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField(
        "I am a", choices=[("patient", "Patient"), ("doctor", "Doctor")], validators=[DataRequired()]
    )
    specialty = StringField("Specialty (doctors only)", validators=[Optional(), Length(max=120)])
    bio = TextAreaField("Short bio (doctors only)", validators=[Optional(), Length(max=1000)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirm password", validators=[DataRequired(), EqualTo("password", message="Passwords must match")]
    )


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
