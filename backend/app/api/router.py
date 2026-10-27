from fastapi import APIRouter

from app.api.routes.agents import router as agents_router
from app.api.routes.auth import router as auth_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.organizations import router as organizations_router
from app.api.routes.crm import router as crm_router
from app.api.routes.inbound import router as inbound_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(dashboard_router)
api_router.include_router(agents_router)
api_router.include_router(knowledge_router)
api_router.include_router(organizations_router)
api_router.include_router(crm_router)
api_router.include_router(inbound_router)
