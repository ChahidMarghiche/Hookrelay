"""Pydantic schemas for the public API.

These define the request/response contract. FastAPI uses them to generate the
OpenAPI spec automatically, so the interactive docs at /docs stay in sync with
the code with zero manual effort.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


class EventStatus(str, Enum):
    pending = "pending"      # accepted, waiting for (or between) delivery attempts
    delivered = "delivered"  # destination returned a 2xx
    failed = "failed"        # retries exhausted without success


class RouteCreate(BaseModel):
    """Payload to register a new relay route."""

    destination_url: HttpUrl = Field(..., description="Where matching webhooks are forwarded.")
    description: str = Field("", max_length=200)
    signing_secret: str | None = Field(
        None,
        description="If set, incoming requests must carry a valid HMAC-SHA256 "
        "signature in the X-Hookrelay-Signature header.",
    )
    forward_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Extra headers attached to every forwarded request.",
    )
    max_retries: int = Field(5, ge=0, le=20)


class Route(RouteCreate):
    id: str
    created_at: datetime


class AttemptOut(BaseModel):
    number: int
    attempted_at: datetime
    success: bool
    status_code: int | None = None
    error: str | None = None


class EventOut(BaseModel):
    id: str
    route_id: str
    received_at: datetime
    status: EventStatus
    attempt_count: int


class EventDetail(EventOut):
    attempts: list[AttemptOut]
