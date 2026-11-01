import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# Looked for next to this package and up to the repo root, so it works whatever directory uvicorn
# was started from - a deployed backend has no cwd-relative .env.
load_dotenv()

# `or`, not a default argument: a DATABASE_URL that is set but blank is Render's way of saying
# "not configured", and an empty string is not a URL - it is the wedge that made uvicorn sit there
# printing nothing.
URL = os.getenv("DATABASE_URL") or "sqlite:///./coldchain.db"

# Three shapes mean the same Postgres and only psycopg2 (the one driver this project pins) has to end
# up underneath them: the short postgres:// that libpq stopped accepting, the long form, and the
# +driver spellings SQLAlchemy accepts for drivers that are not installed here.
scheme, sep, rest = URL.partition("://")
if sep and scheme.startswith("postgres"):
    URL = f"postgresql://{rest}"

# SQLite refuses to share a connection across threads unless told to; a real server has its own pool,
# and needs a connect timeout or an unreachable host costs a two-minute hang instead of an error.
if URL.startswith("sqlite"):
    args = {"check_same_thread": False}
else:
    args = {"connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "5"))}

engine = create_engine(URL, connect_args=args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def describe_target(url=URL):
    """Where the database is thought to be, in a form that is safe to print.

    The URL carries a password, so this rebuilds the interesting part from the parsed pieces instead
    of echoing it: host, port, database name. A pasteable error line must be safe to post in a
    group chat.
    """
    try:
        u = make_url(url)
    except Exception:
        return "<unparseable DATABASE_URL>"
    if u.drivername.startswith("sqlite"):
        return u.database or ":memory:"
    return f"{u.host}:{u.port or 5432}/{u.database}"


def check_connection():
    """One query before anything is created or served.

    Without it a wrong DATABASE_URL shows up as uvicorn standing in create_all with no output at all,
    which reads as a hung server rather than a connection refused. This prints the one line that
    names the target and stops, instead of a traceback wall about SQLAlchemy internals.
    """
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception:
        sys.stderr.write(f"Cannot reach the database at {describe_target()}. "
                         f"Unset DATABASE_URL to use local SQLite.\n")
        sys.stderr.flush()
        raise SystemExit(1)


check_connection()


# ডিপেনডেন্সি ডাটাবেস সেশন পাওয়ার জন্য
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
