from datetime import UTC

import asyncio

import httpx
import pytest
import respx

from app import delivery, store
from app.models import EventStatus, RouteCreate

DEST = "https://downstream.test/webhook"


def _route(max_retries=3):
    return store.create_route(
        RouteCreate(destination_url=DEST, description="d", max_retries=max_retries)
    )


def _due_event(event_id):
    # Re-read the event row the way the worker would.
    from datetime import datetime
    rows = store.get_due_events(datetime.now(UTC))
    return next(r for r in rows if r["id"] == event_id)


@respx.mock
@pytest.mark.asyncio
async def test_successful_delivery_marks_delivered():
    route = _route()
    respx.post(DEST).mock(return_value=httpx.Response(200))
    event_id = store.create_event(route.id, b"{}", {})

    async with httpx.AsyncClient() as c:
        await delivery.process_event(c, _due_event(event_id))

    detail = store.get_event(event_id)
    assert detail.status == EventStatus.delivered
    assert len(detail.attempts) == 1
    assert detail.attempts[0].success is True
    assert detail.attempts[0].status_code == 200


@respx.mock
@pytest.mark.asyncio
async def test_failure_reschedules_then_exhausts():
    route = _route(max_retries=2)
    respx.post(DEST).mock(return_value=httpx.Response(500))
    event_id = store.create_event(route.id, b"{}", {})

    async with httpx.AsyncClient() as c:
        # First failure -> still pending, rescheduled for a retry.
        await delivery.process_event(c, _due_event(event_id))
        assert store.get_event(event_id).status == EventStatus.pending

        # Wait out the (tiny) backoff window so the event is due again.
        await asyncio.sleep(0.05)
        # Second failure hits the retry ceiling -> failed.
        await delivery.process_event(c, _due_event(event_id))

    detail = store.get_event(event_id)
    assert detail.status == EventStatus.failed
    assert len(detail.attempts) == 2
    assert all(a.success is False for a in detail.attempts)


@respx.mock
@pytest.mark.asyncio
async def test_transport_error_is_recorded():
    route = _route(max_retries=1)
    respx.post(DEST).mock(side_effect=httpx.ConnectError("boom"))
    event_id = store.create_event(route.id, b"{}", {})

    async with httpx.AsyncClient() as c:
        await delivery.process_event(c, _due_event(event_id))

    detail = store.get_event(event_id)
    assert detail.status == EventStatus.failed
    assert "ConnectError" in detail.attempts[0].error


def test_backoff_is_exponential():
    d1 = delivery.backoff_delay(1).total_seconds()
    d2 = delivery.backoff_delay(2).total_seconds()
    d3 = delivery.backoff_delay(3).total_seconds()
    assert d2 == pytest.approx(d1 * 2)
    assert d3 == pytest.approx(d1 * 4)
