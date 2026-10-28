from fastapi import APIRouter

from app.api.v1 import alerts, assets, defects, devices, history, inspections, reports, sensors, stream, system

api_router = APIRouter(prefix="/api/v1")
for m in (system, assets, devices, sensors, inspections, defects, alerts, history, reports, stream):
    api_router.include_router(m.router)
