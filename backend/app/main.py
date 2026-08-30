import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.analytics import router as analytics_router
from app.api.crm import router as crm_router
from app.api.ops import router as ops_router
from app.api.payables import router as payables_router
from app.api.payroll import router as payroll_router
from app.api.router import router
from app.api.tax import router as tax_router
from app.core.config import get_settings
from app.db.integrity import integrity_sqlstate, is_unique_violation
from app.health import readiness, startup_readiness
from app.mcp.server import mcp, mcp_http_app

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if settings.MCP_ENABLED:
        async with mcp.session_manager.run():
            yield
    else:
        yield


app = FastAPI(title=settings.PROJECT_NAME, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.API_PREFIX)
app.include_router(crm_router, prefix=settings.API_PREFIX)
app.include_router(payables_router, prefix=settings.API_PREFIX)
app.include_router(payroll_router, prefix=settings.API_PREFIX)
app.include_router(analytics_router, prefix=settings.API_PREFIX)
app.include_router(tax_router, prefix=settings.API_PREFIX)
app.include_router(ops_router, prefix=settings.API_PREFIX)

if settings.SRI_SIMULATOR_ENABLED:
    from app.integrations.sri.simulator import router as sri_simulator_router

    app.include_router(sri_simulator_router)


@app.middleware("http")
async def correlation_middleware(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    correlation_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = correlation_id
    return response


@app.exception_handler(IntegrityError)
async def integrity_error_handler(
    request: Request,
    exc: IntegrityError,
) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    if not is_unique_violation(exc):
        logger.error(
            "Database integrity error correlation_id=%s error_type=%s sqlstate=%s",
            correlation_id,
            type(exc.orig).__name__,
            integrity_sqlstate(exc),
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": "database_integrity_error",
                "message": "No se pudo guardar el registro",
                "correlationId": correlation_id,
            },
        )
    return JSONResponse(
        status_code=409,
        content={
            "code": "conflict",
            "message": "Ya existe un registro con esos datos",
            "correlationId": correlation_id,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    tenant_id = getattr(request.state, "tenant_id", None)
    actor_id = getattr(request.state, "actor_id", None)
    logger.error(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "error",
                "correlation_id": correlation_id,
                "event": type(exc).__name__,
                "path": request.url.path,
                "tenant": (
                    hashlib.sha256(str(tenant_id).encode()).hexdigest()[:12]
                    if tenant_id is not None
                    else None
                ),
                "actor": str(actor_id) if actor_id is not None else None,
            }
        )
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "Ocurrió un error inesperado",
            "correlationId": correlation_id,
        },
    )


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, str]:
    try:
        dependencies = await readiness()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Dependencies are not ready") from exc
    return {"status": "ok", **dependencies}


@app.get("/health/startup", tags=["health"])
async def startup() -> dict[str, str]:
    try:
        checks = await startup_readiness()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Application startup is not ready") from exc
    return {"status": "ok", **checks}


if settings.MCP_ENABLED:
    app.mount("/", mcp_http_app)
