"""Persistence layer (SQLite).

A thin repository over sqlite3. SQLite keeps the project zero-dependency to run
and trivial to deploy as a single node — a deliberate trade-off for a small
service. The repository boundary means swapping in Postgres + an async driver
later would not touch the API or worker code.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime

from .config import settings
from .models import AttemptOut, EventDetail, EventOut, EventStatus, Route, RouteCreate

_SCHEMA = """
CREATE TABLE IF NOT EXISTS routes (
    id TEXT PRIMARY KEY,
    destination_url TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    signing_secret TEXT,
    forward_headers TEXT NOT NULL DEFAULT '{}',
    max_retries INTEGER NOT NULL DEFAULT 5,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    body BLOB NOT NULL,
    headers TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    attempted_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    status_code INTEGER,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_due ON events(status, next_attempt_at);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)


# --- routes ---------------------------------------------------------------

def create_route(payload: RouteCreate) -> Route:
    route_id = uuid.uuid4().hex
    created = _now()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO routes (id, destination_url, description, signing_secret, "
            "forward_headers, max_retries, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                route_id,
                str(payload.destination_url),
                payload.description,
                payload.signing_secret,
                json.dumps(payload.forward_headers),
                payload.max_retries,
                created.isoformat(),
            ),
        )
    return get_route(route_id)  # type: ignore[return-value]


def get_route(route_id: str) -> Route | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM routes WHERE id = ?", (route_id,)).fetchone()
    return _row_to_route(row) if row else None


def list_routes() -> list[Route]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM routes ORDER BY created_at DESC").fetchall()
    return [_row_to_route(r) for r in rows]


def delete_route(route_id: str) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM routes WHERE id = ?", (route_id,))
    return cur.rowcount > 0


def _row_to_route(row: sqlite3.Row) -> Route:
    return Route(
        id=row["id"],
        destination_url=row["destination_url"],
        description=row["description"],
        signing_secret=row["signing_secret"],
        forward_headers=json.loads(row["forward_headers"]),
        max_retries=row["max_retries"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# --- events ---------------------------------------------------------------

def create_event(route_id: str, body: bytes, headers: dict[str, str]) -> str:
    event_id = uuid.uuid4().hex
    now = _now()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO events (id, route_id, body, headers, status, attempt_count, "
            "next_attempt_at, received_at) VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)",
            (event_id, route_id, body, json.dumps(headers), now.isoformat(), now.isoformat()),
        )
    return event_id


def get_due_events(now: datetime, limit: int = 50) -> list[sqlite3.Row]:
    """Pending events whose next_attempt_at has passed — the worker's queue."""
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE status = 'pending' AND next_attempt_at <= ? "
            "ORDER BY next_attempt_at LIMIT ?",
            (now.isoformat(), limit),
        ).fetchall()


def reschedule_event(event_id: str, next_attempt_at: datetime) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE events SET attempt_count = attempt_count + 1, next_attempt_at = ? "
            "WHERE id = ?",
            (next_attempt_at.isoformat(), event_id),
        )


def finalize_event(event_id: str, status: EventStatus) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE events SET status = ?, attempt_count = attempt_count + 1 WHERE id = ?",
            (status.value, event_id),
        )


def add_attempt(
    event_id: str, number: int, success: bool, status_code: int | None, error: str | None
) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO attempts (event_id, number, attempted_at, success, status_code, error) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, number, _now().isoformat(), int(success), status_code, error),
        )


def get_event(event_id: str) -> EventDetail | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return None
        attempt_rows = conn.execute(
            "SELECT * FROM attempts WHERE event_id = ? ORDER BY number", (event_id,)
        ).fetchall()
    return EventDetail(
        **_row_to_event(row).model_dump(),
        attempts=[
            AttemptOut(
                number=a["number"],
                attempted_at=datetime.fromisoformat(a["attempted_at"]),
                success=bool(a["success"]),
                status_code=a["status_code"],
                error=a["error"],
            )
            for a in attempt_rows
        ],
    )


def list_events(route_id: str) -> list[EventOut]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE route_id = ? ORDER BY received_at DESC", (route_id,)
        ).fetchall()
    return [_row_to_event(r) for r in rows]


def _row_to_event(row: sqlite3.Row) -> EventOut:
    return EventOut(
        id=row["id"],
        route_id=row["route_id"],
        received_at=datetime.fromisoformat(row["received_at"]),
        status=EventStatus(row["status"]),
        attempt_count=row["attempt_count"],
    )
