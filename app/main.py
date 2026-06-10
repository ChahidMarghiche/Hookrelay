"""HTTP API and application wiring.

Endpoints:
  POST   /routes            register a relay route
  GET    /routes            list routes
  GET    /routes/{id}       fetch one route
  DELETE /routes/{id}       remove a route
  POST   /ingest/{id}       receive a webhook for a route (signature-checked)
  GET    /routes/{id}/events  list events for a route
  GET    /events/{id}       event detail incl. every delivery attempt
  GET    /healthz           liveness probe

Interactive OpenAPI docs are served at /docs.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response

from . import security, store
from .delivery import worker_loop
from .models import EventDetail, EventOut, Route, RouteCreate


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure schema exists and launch the background delivery worker.
    store.init_db()
    stop = asyncio.Event()
    task = asyncio.create_task(worker_loop(stop))
    try:
        yield
    finally:
        # Graceful shutdown: signal the worker and wait for it to drain.
        stop.set()
        await task


app = FastAPI(
    title="Hookrelay",
    version="1.0.0",
    summary="A self-hostable webhook relay & automation gateway with signature "
    "verification, retries, and delivery observability.",
    lifespan=lifespan,
)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/routes", response_model=Route, status_code=201, tags=["routes"])
def create_route(payload: RouteCreate) -> Route:
    return store.create_route(payload)


@app.get("/routes", response_model=list[Route], tags=["routes"])
def list_routes() -> list[Route]:
    return store.list_routes()


@app.get("/routes/{route_id}", response_model=Route, tags=["routes"])
def get_route(route_id: str) -> Route:
    route = store.get_route(route_id)
    if route is None:
        raise HTTPException(404, "route not found")
    return route


@app.delete("/routes/{route_id}", status_code=204, tags=["routes"])
def delete_route(route_id: str) -> Response:
    if not store.delete_route(route_id):
        raise HTTPException(404, "route not found")
    return Response(status_code=204)


@app.post("/ingest/{route_id}", status_code=202, tags=["ingest"])
async def ingest(route_id: str, request: Request) -> dict[str, str]:
    """Accept a webhook, verify it, and queue it for delivery.

    Returns 202 Accepted immediately — delivery happens asynchronously so the
    sender is never blocked on a slow or flaky destination.
    """
    route = store.get_route(route_id)
    if route is None:
        raise HTTPException(404, "route not found")

    body = await request.body()

    if route.signing_secret:
        provided = request.headers.get(security.SIGNATURE_HEADER)
        if not security.verify(route.signing_secret, body, provided):
            raise HTTPException(401, "invalid or missing signature")

    forwardable = {k: v for k, v in request.headers.items()
                   if k.lower() not in {"host", "content-length", security.SIGNATURE_HEADER}}
    event_id = store.create_event(route_id, body, forwardable)
    return {"event_id": event_id, "status": "accepted"}


@app.get("/routes/{route_id}/events", response_model=list[EventOut], tags=["events"])
def list_events(route_id: str) -> list[EventOut]:
    if store.get_route(route_id) is None:
        raise HTTPException(404, "route not found")
    return store.list_events(route_id)


@app.get("/events/{event_id}", response_model=EventDetail, tags=["events"])
def get_event(event_id: str) -> EventDetail:
    event = store.get_event(event_id)
    if event is None:
        raise HTTPException(404, "event not found")
    return event
