from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.service import AuthService
from app.projects import schemas
from app.projects.service import ProjectService

router = APIRouter()
security = HTTPBearer()


async def get_current_user(token: str = Depends(security), db: Session = Depends(get_db)):
    """Dependency to get current authenticated user"""
    auth_service = AuthService(db)
    user = await auth_service.get_current_user(token.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    return user


@router.get("/", response_model=List[schemas.ProjectWithPermissions])
async def list_projects(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all projects accessible to the current user"""
    project_service = ProjectService(db)
    return await project_service.list_user_projects(current_user.id)


@router.post("/", response_model=schemas.Project)
async def create_project(
    project: schemas.ProjectCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new project"""
    project_service = ProjectService(db)
    return await project_service.create_project(project, current_user.id)


@router.get("/{project_id}", response_model=schemas.ProjectWithPermissions)
async def get_project(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific project"""
    project_service = ProjectService(db)
    project = await project_service.get_project(project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}", response_model=schemas.Project)
async def update_project(
    project_id: int,
    project_update: schemas.ProjectUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a project"""
    project_service = ProjectService(db)
    project = await project_service.update_project(project_id, project_update, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or access denied")
    return project


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a project"""
    project_service = ProjectService(db)
    success = await project_service.delete_project(project_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found or access denied")
    return {"message": "Project deleted successfully"}


@router.post("/{project_id}/members", response_model=schemas.ProjectMember)
async def add_project_member(
    project_id: int,
    member: schemas.ProjectMemberBase,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a member to a project"""
    project_service = ProjectService(db)
    return await project_service.add_member(project_id, member, current_user.id)


@router.delete("/{project_id}/members/{member_id}")
async def remove_project_member(
    project_id: int,
    member_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a member from a project"""
    project_service = ProjectService(db)
    success = await project_service.remove_member(project_id, member_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found or access denied")
    return {"message": "Member removed successfully"}