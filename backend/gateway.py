from fastapi import FastAPI

from app.main import app as customer_app
from discovery_engine.main import app as discovery_engine_app

app = FastAPI(
    title="JSAN GeoDiscover Executive Customer Demo",
    version="5.0.0",
    description="Executive customer demonstration with an internal discovery engine retained for future scale",
)

@app.get("/integrated-health")
def integrated_health():
    return {
        "status": "healthy",
        "version": "5.0.0",
        "customer_workspace": "/",
        "live_discovery_engine": "/engine/",
    }

# Mount the more specific path first, then the customer workspace at root.
app.mount("/engine", discovery_engine_app)
app.mount("/", customer_app)
