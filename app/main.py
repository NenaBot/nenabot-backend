"""FastAPI application factory and OpenAPI schema customization.

This module initializes the FastAPI application, sets up CORS middleware,
and extends the OpenAPI specification to include SSE-related schemas for
real-time job event streaming.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.routes import router
from app.dependencies import get_orchestrator
from app.schemas import JobEvent

logger = logging.getLogger("app")
request_logger = logging.getLogger("app.request")


def _configure_app_logging() -> None:
    """Route app loggers through Uvicorn handlers for consistent output."""
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    root_logger = logging.getLogger()
    app_logger = logging.getLogger("app")
    app_request_logger = logging.getLogger("app.request")

    def _is_access_formatter(handler: logging.Handler) -> bool:
        formatter = getattr(handler, "formatter", None)
        return (
            formatter is not None and formatter.__class__.__name__ == "AccessFormatter"
        )

    selected_handlers: list[logging.Handler] = []
    if uvicorn_error_logger.handlers:
        selected_handlers = list(uvicorn_error_logger.handlers)
    elif root_logger.handlers:
        selected_handlers = list(root_logger.handlers)

    selected_handlers = [h for h in selected_handlers if not _is_access_formatter(h)]
    if not selected_handlers:
        fallback_handler = logging.StreamHandler()
        fallback_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        selected_handlers = [fallback_handler]

    app_logger.handlers = selected_handlers
    app_request_logger.handlers = selected_handlers
    app_logger.propagate = False
    app_request_logger.propagate = False

    app_logger.setLevel(logging.INFO)
    app_request_logger.setLevel(logging.INFO)

    app_logger.info(
        "Configured app logging handlers=%d app_level=%s request_level=%s root_level=%s",
        len(selected_handlers),
        logging.getLevelName(app_logger.level),
        logging.getLevelName(app_request_logger.level),
        logging.getLevelName(root_logger.level),
    )


def _custom_openapi(app: FastAPI) -> dict:
    """Extend the auto-generated OpenAPI spec with SSE-related schemas."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    # Inject JobEvent (not used as a regular response model, but referenced
    # by the SSE endpoint's response schema).
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    je = JobEvent.model_json_schema(
        mode="serialization", ref_template="#/components/schemas/{model}"
    )
    # Hoist nested $defs into the top-level schemas so $refs resolve.
    for name, sub in je.pop("$defs", {}).items():
        schemas.setdefault(name, sub)
    schemas["JobEvent"] = je
    app.openapi_schema = schema
    return schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_app_logging()
    logger.info("Application lifespan startup begin")
    # Run blocking startup (robot connect + optional homing) in a thread.
    loop = asyncio.get_event_loop()
    orchestrator = await loop.run_in_executor(None, get_orchestrator)

    try:
        await orchestrator.initialize_ionvision()
    except Exception:
        logging.getLogger("app").warning(
            "IonVision websocket initialization failed; continuing without event stream",
            exc_info=True,
        )

    try:
        yield
    finally:
        logger.info("Application lifespan shutdown begin")
        try:
            await orchestrator.close_camera()
        except Exception:
            logging.getLogger("app").warning(
                "Camera shutdown failed",
                exc_info=True,
            )
        try:
            await orchestrator.close_ionvision()
        except Exception:
            logging.getLogger("app").warning(
                "IonVision websocket shutdown failed",
                exc_info=True,
            )


def create_app() -> FastAPI:
    app = FastAPI(title="Olfactomics Orchestrator", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def log_request_timing(request, call_next):
        start = time.perf_counter()
        method = request.method
        path = request.url.path
        query = request.url.query
        full_path = f"{path}?{query}" if query else path

        request_logger.info("REQ start method=%s path=%s", method, full_path)
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            request_logger.exception(
                "REQ error method=%s path=%s duration_ms=%.2f",
                method,
                full_path,
                duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        request_logger.info(
            "REQ done method=%s path=%s status=%d duration_ms=%.2f",
            method,
            full_path,
            response.status_code,
            duration_ms,
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    app.openapi = lambda: _custom_openapi(app)  # type: ignore[assignment]
    return app


app = create_app()
