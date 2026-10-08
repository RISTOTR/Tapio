from fastapi import FastAPI

from apps.api.app.routers.health import router

app = FastAPI(title="Tapio", version="0.1.0")
app.include_router(router)
