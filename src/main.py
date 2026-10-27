import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text

from src.api.v1.auth import router as auth_router
from src.api.v1.disputes import router as disputes_router
from src.api.v1.escrow import router as escrow_router
from src.api.v1.ledger import router as ledger_router
from src.api.v1.reconciliation import router as reconciliation_router
from src.api.v1.webhooks import router as webhooks_router
from src.core.config import get_settings
from src.core.database import Base, engine

settings = get_settings()

# Prometheus Metrics instrumentation
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests processed", ["method", "endpoint", "status_code"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency in seconds", ["endpoint"])
LEDGER_POSTING_COUNT = Counter("ledger_postings_total", "Total double-entry ledger postings posted", ["reference_type"])
ESCROW_TRANSITION_COUNT = Counter("escrow_transitions_total", "Total escrow state machine transitions", ["to_state"])

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp":"%(asctime)s", "level":"%(levelname)s", "logger":"%(name)s", "message":"%(message)s"}',
)
logger = logging.getLogger("escrowatt")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Ensure tables exist on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Escrowatt database schema initialized successfully")
    yield
    await engine.dispose()
    logger.info("Escrowatt database engine shut down")


app = FastAPI(
    title="Escrowatt API",
    description="Production-grade Escrow Marketplace Backend for Solar Equipment Procurement in India",
    version=settings.VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.perf_counter()

    response = await call_next(request)

    duration = time.perf_counter() - start_time
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{duration * 1000:.2f}ms"

    # Track metrics
    path = request.url.path
    if not path.startswith("/metrics") and not path.startswith("/health"):
        REQUEST_COUNT.labels(method=request.method, endpoint=path, status_code=response.status_code).inc()
        REQUEST_LATENCY.labels(endpoint=path).observe(duration)

    return response


# Landing Website
STATIC_DIR = Path(__file__).parent / "static"


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
async def serve_homepage():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Ampvault Escrow Platform</h1><p>API docs at <a href='/docs'>/docs</a></p>")


# Health & Telemetry
@app.get("/health/live", tags=["Health"])
async def liveness_probe():
    return {"status": "alive", "service": "escrowatt"}


@app.get("/health/ready", tags=["Health"])
async def readiness_probe():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return Response(
            content=f'{{"status":"not_ready","error":"{str(e)}"}}',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/json",
        )


@app.get("/metrics", tags=["Telemetry"])
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Mount Version 1 Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(escrow_router, prefix="/api/v1")
app.include_router(ledger_router, prefix="/api/v1")
app.include_router(disputes_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(reconciliation_router, prefix="/api/v1")
