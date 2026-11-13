"""QuantLab local accounts and opaque sessions."""
import hashlib
import hmac
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore

from repositories.mysql_store import connect

_PASSWORD_WORKERS = BoundedSemaphore(2)


@contextmanager
def transaction():
    with connect() as connection:
        with connection.cursor() as cursor:
            yield cursor
        connection.commit()


def initialize(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ql_auth_users (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            username VARCHAR(100) NOT NULL UNIQUE,
            display_name VARCHAR(100) NOT NULL,
            password_hash VARCHAR(200) NOT NULL,
            role VARCHAR(20) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ql_auth_sessions (
            token_hash CHAR(64) PRIMARY KEY,
            user_id BIGINT NOT NULL,
            expires_at DATETIME NOT NULL,
            INDEX (expires_at),
            FOREIGN KEY (user_id) REFERENCES ql_auth_users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def password_hash(password, salt=None):
    salt = salt if salt is not None else secrets.token_bytes(16)
    with _PASSWORD_WORKERS:
        digest = hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256*1024**2)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password, stored):
    salt = bytes.fromhex(stored.split(":", 1)[0]) if stored else bytes(16)
    calculated = password_hash(password, salt)
    return hmac.compare_digest(calculated, stored or "")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def authenticate(username, password, lifetime):
    with transaction() as cursor:
        initialize_audit(cursor)
        cursor.execute("SELECT id, username, display_name, role, enabled, password_hash FROM ql_auth_users WHERE username=%s FOR UPDATE", (username,))
        user = cursor.fetchone()
        valid = verify_password(password, user["password_hash"] if user else None)
        if not valid or not user or not user["enabled"]:
            audit(cursor, username, "login_failed")
            return None
        token = secrets.token_urlsafe(32)
        now = utc_now()
        cursor.execute("DELETE FROM ql_auth_sessions WHERE expires_at <= %s", (now,))
        cursor.execute("INSERT INTO ql_auth_sessions VALUES (%s,%s,%s)", (token_hash(token), user["id"], now + timedelta(seconds=lifetime)))
        audit(cursor, user["username"], "login")
        return token, {key: user[key] for key in ("id", "username", "display_name", "role")}


def session_user(token):
    with transaction() as cursor:
        cursor.execute("""
            SELECT u.id, u.username, u.display_name, u.role
            FROM ql_auth_sessions s JOIN ql_auth_users u ON u.id=s.user_id
            WHERE s.token_hash=%s AND s.expires_at>%s AND u.enabled=TRUE
        """, (token_hash(token), utc_now()))
        return cursor.fetchone()


def revoke(token):
    with transaction() as cursor:
        cursor.execute("DELETE FROM ql_auth_sessions WHERE token_hash=%s", (token_hash(token),))

def initialize_audit(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ql_auth_audit (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            actor VARCHAR(100) NOT NULL,
            action VARCHAR(32) NOT NULL,
            target VARCHAR(100) NOT NULL,
            created_at DATETIME NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def audit(cursor, actor, action, target=""):
    cursor.execute(
        "INSERT INTO ql_auth_audit (actor, action, target, created_at) VALUES (%s,%s,%s,%s)",
        (actor, action, target, utc_now()),
    )
