from fastapi import APIRouter

from app.auth.routes import router as auth_router
from app.projects.routes import router as projects_router
from app.kanban.routes import router as kanban_router
from app.ai.routes import router as ai_router

router = APIRouter()

router.include_router(auth_router, prefix="/auth", tags=["authentication"])
router.include_router(projects_router, prefix="/projects", tags=["projects"]) 
router.include_router(kanban_router, prefix="/kanban", tags=["kanban"])
router.include_router(ai_router, prefix="/ai", tags=["ai"])