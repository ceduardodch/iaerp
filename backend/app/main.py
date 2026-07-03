import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.router import router
from app.core.config import get_settings
from app.health import readiness, startup_readiness
from app.mcp.server import mcp, mcp_http_app

settings = get_settings()


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
    _exc: IntegrityError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "code": "conflict",
            "message": "A record with the same business key already exists",
            "correlationId": request.state.correlation_id,
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
