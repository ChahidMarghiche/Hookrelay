# Hookrelay — a reliable webhook relay & automation gateway

> **Personal project** built to demonstrate backend API design and DevOps practice.
> Not a client engagement. All metrics below are reproducible from this repo.

A self-hostable service that sits between a webhook **sender** (Stripe, GitHub,
Shopify, an internal system…) and a **destination**. It authenticates incoming
webhooks, accepts them instantly, and then delivers them reliably — retrying with
exponential backoff and recording every attempt so you can see exactly what
happened to each event.

```
  sender ──POST /ingest/{route}──▶  Hookrelay  ──forward (with retries)──▶  destination
                                       │
                                  persists every event + attempt
                                       │
                                  GET /events/{id}  ◀── full delivery history
```

## The problem it solves

A naive relay forwards a webhook once. If the destination is down for ten
seconds — a deploy, a blip — the event is lost forever, and you have no record
it ever existed. For anything tied to payments or orders, that is a silent data
loss bug. Hookrelay treats delivery as a durable, observable process instead of
a fire-and-forget HTTP call.

## What it demonstrates

| Area | What's shown |
|------|--------------|
| **API design** | Clean REST resource model, correct status codes (201/202/204/401/404), auto-generated OpenAPI docs at `/docs` |
| **Security** | HMAC-SHA256 signature verification of incoming webhooks, constant-time comparison |
| **Reliability engineering** | Async background worker, exponential backoff, retry ceiling, durable event store, graceful shutdown |
| **Observability** | Every delivery attempt is recorded and queryable per-event |
| **DevOps** | Dockerfile (non-root, healthcheck), docker-compose, GitHub Actions pipeline (lint → test → build) |
| **Testing** | 16 tests covering API, security, and the retry state machine (HTTP mocked with `respx`) |

## Architecture

| Module | Responsibility |
|--------|----------------|
| `app/main.py` | FastAPI app, routes, lifespan that launches/stops the worker |
| `app/store.py` | SQLite persistence (routes, events, attempts) behind a thin repository |
| `app/delivery.py` | Forwarding, exponential backoff, the background worker loop |
| `app/security.py` | HMAC signing & verification |
| `app/models.py` | Pydantic schemas (the OpenAPI contract) |

**Design trade-off, made explicit:** storage is SQLite and the worker runs
in-process. That keeps the service a single, zero-dependency deployable — the
right call at small scale. The repository boundary means moving to Postgres +
an async driver, or to an external queue, would not touch the API or worker
logic. That's the documented path to horizontal scale.

## Run it

```bash
# Local (Python 3.11+)
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://localhost:8000/docs

# Or with Docker
docker compose up --build
```

## Try it in 30 seconds

```bash
# 1. Create a route pointing at any test endpoint
curl -s localhost:8000/routes -H 'content-type: application/json' \
  -d '{"destination_url":"https://httpbin.org/post","description":"demo"}'

# 2. Send it a webhook (use the id from step 1)
curl -s -X POST localhost:8000/ingest/<ROUTE_ID> -d '{"hello":"world"}'

# 3. Inspect the delivery history
curl -s localhost:8000/events/<EVENT_ID>
```

## Test & lint

```bash
ruff check .     # lint — passes clean
pytest -q        # 16 passed
```

The same two commands run in CI on every push (`.github/workflows/ci.yml`); the
container image is only built if they pass.

## What I'd add next

- Persisted queue / Postgres for multi-node deployments
- Per-route delivery metrics endpoint (success rate, p95 latency) + Prometheus export
- A signing option for **outgoing** requests so destinations can verify Hookrelay
- Dead-letter inspection & manual replay UI

---

Built by **[Chahid Marghiche]** · [github](https://github.com/ChahidMarghiche)