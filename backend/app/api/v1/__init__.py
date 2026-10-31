from fastapi import APIRouter

from app.api.v1 import alerts, assets, cameras, defects, devices, history, inspections, reports, sensors, stream, system

api_router = APIRouter(prefix="/api/v1")
for m in (system, assets, devices, sensors, inspections, cameras, defects, alerts, history, reports, stream):
    api_router.include_router(m.router)

# GET /api/v1 and /api/v1/ — API index (the "API base" link in Settings)
api_router.add_api_route("", system.api_index, methods=["GET"], tags=["system"])
api_router.add_api_route("/", system.api_index, methods=["GET"], include_in_schema=False)
