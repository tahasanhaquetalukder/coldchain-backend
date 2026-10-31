from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# লোকাল ডেভেলপমেন্ট ও হ্যাকাথনের জন্য SQLite ডাটাবেস ইউআরএল
SQLALCHEMY_DATABASE_URL = "sqlite:///./coldchain.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# ডিপেনডেন্সি ডাটাবেস সেশন পাওয়ার জন্য
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()