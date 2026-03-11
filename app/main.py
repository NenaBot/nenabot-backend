from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.routes import router
from app.schemas import JobEvent


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


def create_app() -> FastAPI:
    app = FastAPI(title="Olfactomics Orchestrator", version="0.1.0")
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
