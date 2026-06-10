"""Reliable delivery: forwarding, retries with exponential backoff, and the
background worker loop.

The interesting engineering here is reliability. A naive relay forwards once and
drops the event if the destination is briefly down. This one persists every
event, retries on failure with exponential backoff, records each attempt for
observability, and only gives up after a configurable ceiling.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from . import store
from .config import settings
from .models import EventStatus


@dataclass
class AttemptResult:
    success: bool
    status_code: int | None = None
    error: str | None = None


async def forward(client: httpx.AsyncClient, destination: str, body: bytes,
                  headers: dict[str, str]) -> AttemptResult:
    """Make a single forwarding request. A 2xx is success; anything else (or a
    transport error) is a failure that may be retried."""
    try:
        resp = await client.post(
            destination, content=body, headers=headers,
            timeout=settings.delivery_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        return AttemptResult(success=False, error=f"{type(exc).__name__}: {exc}")
    ok = 200 <= resp.status_code < 300
    return AttemptResult(success=ok, status_code=resp.status_code,
                         error=None if ok else f"destination returned {resp.status_code}")


def backoff_delay(attempt_number: int) -> timedelta:
    """Exponential backoff: base * 2**(n-1). Attempt 1 -> base, 2 -> 2x, 3 -> 4x ..."""
    seconds = settings.retry_base_delay_seconds * (2 ** max(0, attempt_number - 1))
    return timedelta(seconds=seconds)


async def process_event(client: httpx.AsyncClient, event: sqlite3.Row) -> None:
    """Attempt to deliver one event and update its state accordingly."""
    route = store.get_route(event["route_id"])
    if route is None:  # route deleted after the event was queued
        store.finalize_event(event["id"], EventStatus.failed)
        return

    attempt_number = event["attempt_count"] + 1
    headers = json.loads(event["headers"])
    headers.update(route.forward_headers)
    # Hop-by-hop headers must not be forwarded verbatim.
    for h in ("host", "content-length", "connection"):
        headers.pop(h, None)

    result = await forward(client, str(route.destination_url), event["body"], headers)
    store.add_attempt(event["id"], attempt_number, result.success,
                      result.status_code, result.error)

    if result.success:
        store.finalize_event(event["id"], EventStatus.delivered)
    elif attempt_number >= route.max_retries:
        store.finalize_event(event["id"], EventStatus.failed)
    else:
        next_at = datetime.now(UTC) + backoff_delay(attempt_number)
        store.reschedule_event(event["id"], next_at)


async def worker_loop(stop: asyncio.Event) -> None:
    """Poll for due events and process them until asked to stop."""
    async with httpx.AsyncClient() as client:
        while not stop.is_set():
            due = store.get_due_events(datetime.now(UTC))
            for event in due:
                await process_event(client, event)
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_interval_seconds)
            except TimeoutError:
                pass  # interval elapsed, poll again
