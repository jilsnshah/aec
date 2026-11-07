"""FastAPI application: wiring, error translation and OpenAPI metadata."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from .api import (
    auth,
    customers,
    enquiries,
    fulfilment,
    integrations,
    inventory,
    orders,
    products,
    purchasing,
)
from .config import get_settings
from .api.auth import require_user
from .database import SessionLocal, engine
from .errors import DomainError
from .logging_config import configure_logging
from .services import auth as auth_service
from .services import background

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

DESCRIPTION = """
Phase 1 business management API: product master, customer master, sales orders
and inventory with **compulsory settlement of pending customer orders**.

Three stock figures are tracked separately for every product and never conflated:

* `physical_stock` -- units actually in the business
* `pending_quantity` -- units still owed on confirmed sales orders
* `net_stock_position` -- `physical_stock - pending_quantity`, which may be negative

When stock is received, `min(received, pending)` units are compulsorily allocated
to outstanding orders before any of the receipt becomes free stock.
"""

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Warn loudly if the schema has not been migrated yet."""
    try:
        tables = set(inspect(engine).get_table_names())
        missing = {"products", "customers", "sales_orders", "stock_movements"} - tables
        if missing:
            logger.error(
                "Database schema is missing tables %s. Run 'alembic upgrade head' in the "
                "backend directory before starting the API.",
                sorted(missing),
            )
    except SQLAlchemyError:
        logger.exception("Could not inspect the database at startup")
    if settings.environment == "production" and settings.secret_key.startswith("dev-only"):
        logger.error(
            "SECRET_KEY is not set. Integration credentials are encrypted with a "
            "development key; set SECRET_KEY to a long random value."
        )
    try:
        with SessionLocal() as session:
            auth_service.ensure_admin(session)
    except SQLAlchemyError:
        logger.exception("Could not create the first admin")
    # Reads the email inbox and pushes queued documents to Tally.
    background.poller.start()
    yield
    background.poller.stop()


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version="1.0.0",
    description=DESCRIPTION,
    openapi_tags=[
        {"name": "products", "description": "Product master."},
        {"name": "customers", "description": "Customer master."},
        {"name": "enquiries", "description": "Customer enquiries and deal finalisation."},
        {"name": "orders", "description": "Sales orders and their fulfilment."},
        {"name": "inventory", "description": "Stock receipts, settlement and audit trail."},
        {"name": "purchasing", "description": "Suppliers, purchase orders and goods receipts."},
        {"name": "fulfilment", "description": "Customer commitments and deliveries."},
        {"name": "integrations", "description": "AI enquiry agent, WhatsApp and email intake."},
        {"name": "auth", "description": "Signing in and out."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Everything needs a signed-in user, except signing in, the health check and
# the webhooks Meta calls.
signed_in = [Depends(require_user)]
app.include_router(auth.router)
app.include_router(integrations.webhooks)
for router in (
    products.router,
    customers.router,
    enquiries.router,
    orders.router,
    inventory.router,
    purchasing.suppliers_router,
    purchasing.po_router,
    purchasing.receipts_router,
    fulfilment.router,
    integrations.router,
):
    app.include_router(router, dependencies=signed_in)


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    # Expected, caller-caused failures: reported, not logged as defects.
    logger.info("%s: %s", exc.code, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "details": exc.details},
    )


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    # Never swallowed: the full traceback goes to the log, a safe summary to the client.
    logger.exception("Database error while handling request", exc_info=exc)
    return JSONResponse(
        status_code=503,
        content={
            "code": "database_error",
            "message": "The database could not complete this operation. No changes were saved.",
            "details": {},
        },
    )


@app.get("/api/health", tags=["inventory"])
def health() -> JSONResponse:
    """Liveness plus a real database round-trip, so a load balancer can rely on it."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check could not reach the database")
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": "unreachable"},
        )
    return JSONResponse(
        content={
            "status": "ok",
            "environment": settings.environment,
            "database": "ok",
        }
    )




class SinglePageApp(StaticFiles):
    """The built web app. Any path that is not a file -- a deep link such as
    /orders/123 -- gets index.html, and the app's router takes it from there."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or path.startswith("api/"):
                raise
            return await super().get_response("index.html", scope)


# Mounted last, so every /api route above takes precedence.
if settings.frontend_dist:
    dist = Path(settings.frontend_dist)
    if (dist / "index.html").is_file():
        app.mount("/", SinglePageApp(directory=dist, html=True), name="web")
    else:
        logger.error("FRONTEND_DIST=%s has no index.html; the web app is not served.", dist)
