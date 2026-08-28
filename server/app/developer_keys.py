from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

KEY_PREFIX = "vsk_live_"
KEY_MASK = "\u2022" * 8
KEY_RANDOM_BYTES = 32
MAX_DEVELOPER_NAME_LENGTH = 120

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS developer_api_keys (
    id uuid PRIMARY KEY,
    developer_name text NOT NULL CHECK (length(btrim(developer_name)) > 0),
    key_hash text NOT NULL UNIQUE,
    key_prefix text NOT NULL,
    key_last4 text NOT NULL CHECK (length(key_last4) = 4),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz
);

CREATE INDEX IF NOT EXISTS developer_api_keys_active_hash_idx
    ON developer_api_keys (key_hash)
    WHERE active;
"""


class DeveloperKeyStoreNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class DeveloperApiKeyRecord:
    id: str
    developer_name: str
    key_prefix: str
    key_last4: str
    active: bool
    created_at: datetime | str
    revoked_at: datetime | str | None = None

    @property
    def masked_key(self) -> str:
        return mask_api_key(self.key_prefix, self.key_last4)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "developer_name": self.developer_name,
            "key_prefix": self.key_prefix,
            "key_last4": self.key_last4,
            "masked_key": self.masked_key,
            "active": self.active,
            "created_at": self.created_at,
            "revoked_at": self.revoked_at,
        }


def clean_developer_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Developer name is required")
    if len(cleaned) > MAX_DEVELOPER_NAME_LENGTH:
        raise ValueError(f"Developer name exceeds {MAX_DEVELOPER_NAME_LENGTH} characters")
    return cleaned


def generate_api_key() -> str:
    return f"{KEY_PREFIX}{secrets.token_urlsafe(KEY_RANDOM_BYTES)}"


def mask_api_key(prefix: str, last4: str) -> str:
    return f"{prefix}{KEY_MASK}{last4}"


def hash_api_key(api_key: str, hash_secret: str) -> str:
    return hmac.new(
        hash_secret.encode("utf-8"),
        api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def is_postgres_dsn(value: str | None) -> bool:
    if not value:
        return False
    return urlparse(value).scheme in {"postgres", "postgresql"}


def _record_from_row(row: dict[str, Any]) -> DeveloperApiKeyRecord:
    return DeveloperApiKeyRecord(
        id=str(row["id"]),
        developer_name=row["developer_name"],
        key_prefix=row["key_prefix"],
        key_last4=row["key_last4"],
        active=row["active"],
        created_at=row["created_at"],
        revoked_at=row["revoked_at"],
    )


class DisabledDeveloperApiKeyStore:
    configured = False

    def ensure_schema(self):
        raise DeveloperKeyStoreNotConfigured(
            "Developer API key storage is not configured."
        )

    def list(self) -> list[DeveloperApiKeyRecord]:
        self.ensure_schema()

    def create(self, developer_name: str) -> tuple[DeveloperApiKeyRecord, str]:
        self.ensure_schema()

    def revoke(self, key_id: str) -> DeveloperApiKeyRecord | None:
        self.ensure_schema()

    def authenticate(self, api_key: str) -> DeveloperApiKeyRecord | None:
        self.ensure_schema()


class PostgresDeveloperApiKeyStore:
    configured = True

    def __init__(self, dsn: str, hash_secret: str):
        self.dsn = dsn
        self.hash_secret = hash_secret
        self._schema_ready = False
        self._schema_lock = Lock()

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.dsn, connect_timeout=10, row_factory=dict_row)

    def ensure_schema(self):
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connect() as conn:
                conn.execute(SCHEMA_SQL)
            self._schema_ready = True

    def list(self) -> list[DeveloperApiKeyRecord]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, developer_name, key_prefix, key_last4, active, created_at, revoked_at
                FROM developer_api_keys
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def create(self, developer_name: str) -> tuple[DeveloperApiKeyRecord, str]:
        self.ensure_schema()
        clean_name = clean_developer_name(developer_name)

        for _ in range(3):
            api_key = generate_api_key()
            record_id = uuid4()
            key_hash = hash_api_key(api_key, self.hash_secret)
            key_last4 = api_key[-4:]

            try:
                with self._connect() as conn:
                    row = conn.execute(
                        """
                        INSERT INTO developer_api_keys (
                            id, developer_name, key_hash, key_prefix, key_last4
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id, developer_name, key_prefix, key_last4, active, created_at, revoked_at
                        """,
                        (record_id, clean_name, key_hash, KEY_PREFIX, key_last4),
                    ).fetchone()
                return _record_from_row(row), api_key
            except Exception as exc:
                if exc.__class__.__name__ != "UniqueViolation":
                    raise

        raise RuntimeError("Could not generate a unique developer API key")

    def revoke(self, key_id: str) -> DeveloperApiKeyRecord | None:
        self.ensure_schema()
        try:
            record_id = UUID(key_id)
        except ValueError:
            return None

        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE developer_api_keys
                SET active = false,
                    revoked_at = COALESCE(revoked_at, now())
                WHERE id = %s
                RETURNING id, developer_name, key_prefix, key_last4, active, created_at, revoked_at
                """,
                (record_id,),
            ).fetchone()
        return _record_from_row(row) if row else None

    def authenticate(self, api_key: str) -> DeveloperApiKeyRecord | None:
        if not api_key.startswith(KEY_PREFIX):
            return None

        self.ensure_schema()
        key_hash = hash_api_key(api_key, self.hash_secret)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, developer_name, key_prefix, key_last4, active, created_at, revoked_at
                FROM developer_api_keys
                WHERE key_hash = %s AND active = true
                LIMIT 1
                """,
                (key_hash,),
            ).fetchone()

        if row is None:
            return None
        return _record_from_row(row)


def build_developer_api_key_store(settings) -> DisabledDeveloperApiKeyStore | PostgresDeveloperApiKeyStore:
    dsn = settings.developer_api_keys_database_url or settings.database_url
    if not is_postgres_dsn(dsn):
        return DisabledDeveloperApiKeyStore()

    hash_secret = settings.developer_api_key_hash_secret or settings.api_key
    return PostgresDeveloperApiKeyStore(dsn, hash_secret)
