from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class DuplicateUser(ValueError):
    pass


class CooldownActive(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class User:
    id: str
    name: str
    email: str
    phone: str
    password_hash: str


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    user: User
    csrf_token: str


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    phone TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions(expires_at);
                CREATE TABLE IF NOT EXISTS call_attempts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    http_status INTEGER,
                    session_id TEXT,
                    error TEXT,
                    created_at INTEGER NOT NULL,
                    completed_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS call_attempts_user_created_idx
                    ON call_attempts(user_id, created_at DESC);
                """
            )

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            phone=row["phone"],
            password_hash=row["password_hash"],
        )

    def create_user(self, *, name: str, email: str, phone: str, password_hash: str) -> User:
        user = User(str(uuid4()), name, email, phone, password_hash)
        try:
            with self.connect() as connection:
                connection.execute(
                    "INSERT INTO users (id, name, email, phone, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (user.id, user.name, user.email, user.phone, user.password_hash, int(time.time())),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateUser("email or phone already exists") from exc
        return user

    def get_user_by_email(self, email: str) -> User | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return self._row_to_user(row) if row else None

    def create_session(self, *, user_id: str, token_hash: str, csrf_token: str, ttl_seconds: int) -> None:
        now = int(time.time())
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, csrf_token, created_at, last_seen_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (token_hash, user_id, csrf_token, now, now, now + ttl_seconds),
            )

    def get_session(self, token_hash: str) -> AuthenticatedSession | None:
        now = int(time.time())
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT users.*, sessions.csrf_token
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
            if not row:
                return None
            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )
        return AuthenticatedSession(self._row_to_user(row), row["csrf_token"])

    def delete_session(self, token_hash: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def reserve_call(self, *, user_id: str, cooldown_seconds: int) -> str:
        now = int(time.time())
        attempt_id = str(uuid4())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            recent = connection.execute(
                """
                SELECT 1 FROM call_attempts
                WHERE user_id = ? AND status IN ('pending', 'accepted') AND created_at > ?
                LIMIT 1
                """,
                (user_id, now - cooldown_seconds),
            ).fetchone()
            if recent:
                raise CooldownActive("call cooldown is active")
            connection.execute(
                "INSERT INTO call_attempts (id, user_id, status, created_at) VALUES (?, ?, 'pending', ?)",
                (attempt_id, user_id, now),
            )
        return attempt_id

    def complete_call(
        self,
        *,
        attempt_id: str,
        accepted: bool,
        http_status: int,
        session_id: str | None,
        error: str | None,
    ) -> None:
        status = "accepted" if accepted else "rejected"
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE call_attempts
                SET status = ?, http_status = ?, session_id = ?, error = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, http_status, session_id, error, int(time.time()), attempt_id),
            )

    def healthcheck(self) -> bool:
        with self.connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1
