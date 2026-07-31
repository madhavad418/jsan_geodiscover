from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import Base, engine
from .routers import (
    audit,
    auth,
    candidates,
    cities,
    connectors,
    costs,
    customer_demo,
    dashboard,
    entity_resolution,
    executive,
    evidence,
    exports,
    imports,
    maps,
    operations,
    projects,
    qa,
    scraping,
    validation,
)

settings = get_settings()
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="JSAN GeoDiscover API",
    version="5.0.0",
    description="Executive customer demonstration focused on current Denpasar comparison evidence, priority sample, cost and scale",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "JSAN GeoDiscover API", "version": "5.0.0"}


for router in [
    auth.router,
    projects.router,
    connectors.router,
    costs.router,
    customer_demo.router,
    imports.router,
    candidates.router,
    entity_resolution.router,
    executive.router,
    cities.router,
    validation.router,
    scraping.router,
    evidence.router,
    qa.router,
    operations.router,
    dashboard.router,
    maps.router,
    exports.router,
    audit.router,
]:
    app.include_router(router, prefix="/api/v1")

app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="frontend")
