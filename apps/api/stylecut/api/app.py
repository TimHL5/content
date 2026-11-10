from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from stylecut.api import dev, health, jobs, projects, references, style_profiles, uploads
from stylecut.api.errors import install_error_handlers, install_unhandled_error_middleware
from stylecut.settings import get_settings

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="StyleCut API", version="0.1.0")
    install_unhandled_error_middleware(app)
    app.add_middleware(  # added last = outermost, so even 500s carry CORS headers
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)

    v1 = APIRouter(prefix=API_PREFIX)
    v1.include_router(health.router)
    v1.include_router(jobs.router)
    v1.include_router(uploads.router)
    v1.include_router(references.router)
    v1.include_router(style_profiles.router)
    v1.include_router(projects.router)
    v1.include_router(projects.public_router)
    if settings.enable_dev_routes:
        v1.include_router(dev.router)
    app.include_router(v1)

    # Unversioned alias for container healthchecks and load balancers.
    app.include_router(health.router, include_in_schema=False)
    return app


app = create_app()
