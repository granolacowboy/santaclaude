from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.projects.models import Project, ProjectMember
from app.projects import schemas
from app.auth.models import User


class ProjectService:
    def __init__(self, db: Session):
        self.db = db
    
    def _check_project_permission(self, project_id: int, user_id: int, required_role: str = None) -> Optional[str]:
        """Check if user has access to project and return their role"""
        # Check if user is owner
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return None
        
        if project.owner_id == user_id:
            return "owner"
        
        # Check membership
        member = self.db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id
        ).first()
        
        if not member:
            return None
        
        return member.role
    
    def _get_user_role_permissions(self, role: str) -> tuple[bool, bool]:
        """Get permissions based on role"""
        if role == "owner":
            return True, True  # can_edit, can_admin
        elif role == "admin":
            return True, True
        elif role == "member":
            return True, False
        elif role == "viewer":
            return False, False
        return False, False
    
    async def list_user_projects(self, user_id: int) -> List[schemas.ProjectWithPermissions]:
        """List all projects accessible to user"""
        # Get projects where user is owner or member
        projects = self.db.query(Project).filter(
            or_(
                Project.owner_id == user_id,
                Project.id.in_(
                    self.db.query(ProjectMember.project_id).filter(
                        ProjectMember.user_id == user_id
                    )
                )
            )
        ).all()
        
        result = []
        for project in projects:
            role = self._check_project_permission(project.id, user_id)
            can_edit, can_admin = self._get_user_role_permissions(role)
            
            project_data = schemas.ProjectWithPermissions(
                **project.__dict__,
                user_role=role,
                can_edit=can_edit,
                can_admin=can_admin
            )
            result.append(project_data)
        
        return result
    
    async def create_project(self, project_create: schemas.ProjectCreate, owner_id: int) -> Project:
        """Create a new project"""
        db_project = Project(
            **project_create.model_dump(),
            owner_id=owner_id
        )
        
        self.db.add(db_project)
        self.db.commit()
        self.db.refresh(db_project)
        
        return db_project
    
    async def get_project(self, project_id: int, user_id: int) -> Optional[schemas.ProjectWithPermissions]:
        """Get a specific project with user permissions"""
        role = self._check_project_permission(project_id, user_id)
        if not role:
            return None
        
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return None
        
        can_edit, can_admin = self._get_user_role_permissions(role)
        
        return schemas.ProjectWithPermissions(
            **project.__dict__,
            user_role=role,
            can_edit=can_edit,
            can_admin=can_admin
        )
    
    async def update_project(
        self, 
        project_id: int, 
        project_update: schemas.ProjectUpdate, 
        user_id: int
    ) -> Optional[Project]:
        """Update a project"""
        role = self._check_project_permission(project_id, user_id)
        can_edit, _ = self._get_user_role_permissions(role)
        
        if not can_edit:
            return None
        
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return None
        
        update_data = project_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(project, field, value)
        
        self.db.commit()
        self.db.refresh(project)
        
        return project
    
    async def delete_project(self, project_id: int, user_id: int) -> bool:
        """Delete a project (only owner can delete)"""
        project = self.db.query(Project).filter(
            Project.id == project_id,
            Project.owner_id == user_id
        ).first()
        
        if not project:
            return False
        
        self.db.delete(project)
        self.db.commit()
        
        return True
    
    async def add_member(
        self, 
        project_id: int, 
        member_data: schemas.ProjectMemberBase, 
        user_id: int
    ) -> schemas.ProjectMember:
        """Add a member to project"""
        role = self._check_project_permission(project_id, user_id)
        _, can_admin = self._get_user_role_permissions(role)
        
        if not can_admin:
            raise ValueError("Access denied: admin privileges required")
        
        # Check if user exists
        user = self.db.query(User).filter(User.id == member_data.user_id).first()
        if not user:
            raise ValueError("User not found")
        
        # Check if already a member
        existing = self.db.query(ProjectMember).filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == member_data.user_id
        ).first()
        
        if existing:
            raise ValueError("User is already a member")
        
        db_member = ProjectMember(
            project_id=project_id,
            user_id=member_data.user_id,
            role=member_data.role
        )
        
        self.db.add(db_member)
        self.db.commit()
        self.db.refresh(db_member)
        
        return db_member
    
    async def remove_member(self, project_id: int, member_id: int, user_id: int) -> bool:
        """Remove a member from project"""
        role = self._check_project_permission(project_id, user_id)
        _, can_admin = self._get_user_role_permissions(role)
        
        if not can_admin:
            return False
        
        member = self.db.query(ProjectMember).filter(
            ProjectMember.id == member_id,
            ProjectMember.project_id == project_id
        ).first()
        
        if not member:
            return False
        
        self.db.delete(member)
        self.db.commit()
        
        return True