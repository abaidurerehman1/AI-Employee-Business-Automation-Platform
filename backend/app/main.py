import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.observability import RequestMetadataMiddleware, configure_logging
from app.db.session import close_connections


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    try:
        yield
    finally:
        await close_connections()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env in {"development", "test"} else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.app_env in {"development", "test"} else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(RequestMetadataMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
                for error in exc.errors()
            ]
        },
    )


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "")
    logging.getLogger("app.errors").error(
        "request_failed",
        extra={"metadata": {"request_id": request_id, "error_type": type(exc).__name__}},
    )
    headers = {
        "X-Request-ID": request_id,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    origin = request.headers.get("origin")
    if origin in settings.cors_origins:
        headers.update(
            {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Expose-Headers": "X-Request-ID",
                "Vary": "Origin",
            }
        )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred", "request_id": request_id},
        headers=headers,
    )


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {"message": settings.app_name, "docs": "/docs"}
