"""Seeds demo doctors so the app isn't empty on first run.

Uses randomuser.me portrait photos — a public dataset of generated/consenting
demo headshots explicitly meant for mockups and test data (not real doctors'
photos), which is the appropriate source for placeholder people in a demo app.
"""

from datetime import time

from app.extensions import db
from app.models import AvailabilitySlot, DoctorProfile, User

DEMO_PASSWORD = "SvasthaDemo@2026"

DEMO_DOCTORS = [
    {
        "name": "Dr. Aditya Sharma",
        "email": "aditya.sharma@svastha.demo",
        "specialty": "Cardiology",
        "city": "Mumbai",
        "years": 14,
        "bio": "Cardiologist focused on preventive heart care, non-invasive diagnostics, and long-term lifestyle management for patients with hypertension and heart disease.",
        "photo": "https://randomuser.me/api/portraits/men/32.jpg",
    },
    {
        "name": "Dr. Priya Nair",
        "email": "priya.nair@svastha.demo",
        "specialty": "Dermatology",
        "city": "Bengaluru",
        "years": 9,
        "bio": "Dermatologist specializing in acne, pigmentation, and skin allergies, with a gentle, evidence-based approach to skincare for all ages.",
        "photo": "https://randomuser.me/api/portraits/women/44.jpg",
    },
    {
        "name": "Dr. Rohan Mehta",
        "email": "rohan.mehta@svastha.demo",
        "specialty": "Orthopedics",
        "city": "Delhi",
        "years": 16,
        "bio": "Orthopedic surgeon treating joint pain, sports injuries, and post-fracture recovery, with a focus on getting patients back to daily life quickly.",
        "photo": "https://randomuser.me/api/portraits/men/56.jpg",
    },
    {
        "name": "Dr. Kavya Reddy",
        "email": "kavya.reddy@svastha.demo",
        "specialty": "Pediatrics",
        "city": "Hyderabad",
        "years": 11,
        "bio": "Pediatrician caring for infants through teens, with special interest in childhood nutrition, vaccination schedules, and early development.",
        "photo": "https://randomuser.me/api/portraits/women/68.jpg",
    },
    {
        "name": "Dr. Arjun Kapoor",
        "email": "arjun.kapoor@svastha.demo",
        "specialty": "General Physician",
        "city": "Pune",
        "years": 8,
        "bio": "General physician for everyday health concerns, chronic condition management, and annual health check-ups for the whole family.",
        "photo": "https://randomuser.me/api/portraits/men/12.jpg",
    },
    {
        "name": "Dr. Sneha Iyer",
        "email": "sneha.iyer@svastha.demo",
        "specialty": "Gynecology",
        "city": "Chennai",
        "years": 13,
        "bio": "Gynecologist offering compassionate care across pregnancy, fertility, and women's reproductive health at every life stage.",
        "photo": "https://randomuser.me/api/portraits/women/23.jpg",
    },
    {
        "name": "Dr. Vikram Singh",
        "email": "vikram.singh@svastha.demo",
        "specialty": "Neurology",
        "city": "Jaipur",
        "years": 18,
        "bio": "Neurologist specializing in migraines, epilepsy, and nerve disorders, combining careful diagnosis with practical treatment plans.",
        "photo": "https://randomuser.me/api/portraits/men/77.jpg",
    },
    {
        "name": "Dr. Anjali Desai",
        "email": "anjali.desai@svastha.demo",
        "specialty": "Psychiatry",
        "city": "Ahmedabad",
        "years": 10,
        "bio": "Psychiatrist providing a calm, judgment-free space for anxiety, depression, sleep issues, and stress-related concerns.",
        "photo": "https://randomuser.me/api/portraits/women/51.jpg",
    },
    {
        "name": "Dr. Rahul Verma",
        "email": "rahul.verma@svastha.demo",
        "specialty": "ENT",
        "city": "Lucknow",
        "years": 12,
        "bio": "ENT specialist treating sinus issues, hearing concerns, and throat infections with a focus on quick, lasting relief.",
        "photo": "https://randomuser.me/api/portraits/men/41.jpg",
    },
    {
        "name": "Dr. Meera Pillai",
        "email": "meera.pillai@svastha.demo",
        "specialty": "Ophthalmology",
        "city": "Kochi",
        "years": 15,
        "bio": "Ophthalmologist offering comprehensive eye exams, vision correction guidance, and care for age-related eye conditions.",
        "photo": "https://randomuser.me/api/portraits/women/8.jpg",
    },
    {
        "name": "Dr. Karan Malhotra",
        "email": "karan.malhotra@svastha.demo",
        "specialty": "Dentistry",
        "city": "Chandigarh",
        "years": 7,
        "bio": "Dentist focused on preventive care, painless root canals, and cosmetic dentistry with a gentle chairside manner.",
        "photo": "https://randomuser.me/api/portraits/men/65.jpg",
    },
    {
        "name": "Dr. Neha Joshi",
        "email": "neha.joshi@svastha.demo",
        "specialty": "General Physician",
        "city": "Nagpur",
        "years": 6,
        "bio": "General physician known for taking time to listen, with a special interest in diabetes and thyroid care.",
        "photo": "https://randomuser.me/api/portraits/women/33.jpg",
    },
]


def seed_demo_data():
    """Idempotent: only seeds if there are no doctors in the database yet."""
    if DoctorProfile.query.first() is not None:
        return

    for entry in DEMO_DOCTORS:
        user = User(email=entry["email"], name=entry["name"], role="doctor")
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
        db.session.flush()

        profile = DoctorProfile(
            user_id=user.id,
            specialty=entry["specialty"],
            bio=entry["bio"],
            photo_url=entry["photo"],
            years_experience=entry["years"],
            clinic_city=entry["city"],
        )
        db.session.add(profile)
        db.session.flush()

        for day in range(0, 5):  # Monday - Friday
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
    print(f"[Svastha] Seeded {len(DEMO_DOCTORS)} demo doctors (password: {DEMO_PASSWORD})")
