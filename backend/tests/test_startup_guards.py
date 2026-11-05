"""The ENV=production guards, in a subprocess because they decide whether the process starts at all.

Each case sets DATABASE_URL to its own file: importing app.main creates tables, and a test that let
it default to ./coldchain.db would have written into the demo database.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# conftest sets several of these for the in-process suite; a guard test that inherited them would be
# testing the fixture rather than the environment it claims to set up.
NOT_INHERITED = {"ENV", "DATABASE_URL", "AUDIT_ANCHOR", "JWT_SECRET", "HMAC_SECRET_KEY", "CORS_ORIGINS",
                 "SEED_ADMIN_PASSWORD", "SEED_PHARMACIST_PASSWORD", "SEED_INSPECTOR_PASSWORD",
                 "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "MAX_BATCHES_PER_FRIDGE"}


def run(code, env):
    tmp = Path(tempfile.mkdtemp()).as_posix()
    base = {k: v for k, v in os.environ.items() if k not in NOT_INHERITED}
    child = {"PYTHONPATH": str(BACKEND), "DATABASE_URL": f"sqlite:///{tmp}/guard.db",
             "AUDIT_ANCHOR": f"{tmp}/anchor.log", **base, **env}
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=str(BACKEND), env=child)
    return p.returncode, p.stdout, p.stderr


IMPORT = "from app import main; print('STARTED')"


def test_production_refuses_the_default_secrets():
    code, out, err = run(IMPORT, {"ENV": "production"})
    assert code != 0 and "STARTED" not in out
    assert "JWT_SECRET" in err and "HMAC_SECRET_KEY" in err


def test_production_refuses_a_missing_secret_entirely():
    code, _, err = run(IMPORT, {"ENV": "production", "JWT_SECRET": "",
                                "HMAC_SECRET_KEY": "CHANGE_ME_FLEET_KEY"})
    assert code != 0 and "JWT_SECRET" in err


def test_production_starts_on_real_secrets():
    code, out, err = run(IMPORT, {"ENV": "production", "JWT_SECRET": "a" * 48,
                                  "HMAC_SECRET_KEY": "b" * 48})
    assert code == 0 and "STARTED" in out, err


def test_production_will_not_seed_a_known_demo_password():
    code, out, err = run(
        "from app import main\n"
        "try:\n"
        "    main.seed_password('admin')\n"
        "    print('SEEDED')\n"
        "except RuntimeError as e:\n"
        "    print('REFUSED', e)\n",
        {"ENV": "production", "JWT_SECRET": "a" * 48, "HMAC_SECRET_KEY": "b" * 48})
    assert code == 0 and "REFUSED" in out and "SEED_ADMIN_PASSWORD" in out, out + err


def test_a_named_seed_password_is_used_verbatim():
    code, out, err = run("from app import main; print(main.seed_password('pharmacist'))",
                         {"ENV": "production", "JWT_SECRET": "a" * 48, "HMAC_SECRET_KEY": "b" * 48,
                          "SEED_PHARMACIST_PASSWORD": "s3cret-nurse"})
    assert code == 0 and "s3cret-nurse" in out, out + err


def test_development_keeps_the_demo_credentials():
    code, out, err = run("from app import main; print(main.seed_password('admin'))",
                         {"ENV": "development"})
    assert code == 0 and "admin123" in out, out + err


def test_the_defaults_never_appear_in_the_source_as_production_values():
    # the guard is only as good as the list it checks
    code, out, err = run("from app import main; print(sorted(main.DEMO_SECRETS))",
                         {"ENV": "development"})
    assert code == 0 and "HMAC_SECRET_KEY" in out and "JWT_SECRET" in out, out + err
