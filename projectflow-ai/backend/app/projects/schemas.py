from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    github_repo_name: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ProjectMemberBase(BaseModel):
    user_id: int
    role: str = "member"


class ProjectMember(ProjectMemberBase):
    id: int
    project_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class Project(ProjectBase):
    id: int
    owner_id: int
    is_active: bool
    github_repo_id: Optional[int] = None
    clone_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    members: List[ProjectMember] = []

    class Config:
        from_attributes = True


class ProjectWithPermissions(Project):
    user_role: Optional[str] = None
    can_edit: bool = False
    can_admin: bool = False