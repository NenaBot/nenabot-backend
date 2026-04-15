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
    # Set log level after uvicorn has configured its own logging
    logging.getLogger("app").setLevel(logging.INFO)
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
