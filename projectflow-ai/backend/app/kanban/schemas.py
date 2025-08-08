from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel


class KanbanCardBase(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "medium"
    labels: List[str] = []
    due_date: Optional[datetime] = None


class KanbanCardCreate(KanbanCardBase):
    column_id: int
    assignee_id: Optional[int] = None


class KanbanCardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column_id: Optional[int] = None
    position: Optional[int] = None
    assignee_id: Optional[int] = None
    priority: Optional[str] = None
    labels: Optional[List[str]] = None
    due_date: Optional[datetime] = None


class KanbanCard(KanbanCardBase):
    id: int
    column_id: int
    position: int
    assignee_id: Optional[int] = None
    ai_agent: Optional[str] = None
    ai_status: str = "idle"
    ai_session_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KanbanColumnBase(BaseModel):
    name: str
    color: Optional[str] = None
    wip_limit: Optional[int] = None


class KanbanColumnCreate(KanbanColumnBase):
    board_id: int
    position: Optional[int] = None


class KanbanColumnUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None
    color: Optional[str] = None
    wip_limit: Optional[int] = None


class KanbanColumn(KanbanColumnBase):
    id: int
    board_id: int
    position: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    cards: List[KanbanCard] = []

    class Config:
        from_attributes = True


class KanbanBoardBase(BaseModel):
    name: str
    description: Optional[str] = None


class KanbanBoardCreate(KanbanBoardBase):
    project_id: int
    is_default: bool = False


class KanbanBoardUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None


class KanbanBoard(KanbanBoardBase):
    id: int
    project_id: int
    is_default: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    columns: List[KanbanColumn] = []

    class Config:
        from_attributes = True


class CardMoveRequest(BaseModel):
    card_id: int
    target_column_id: int
    target_position: int


class CRDTUpdateRequest(BaseModel):
    doc_id: str
    client_id: str
    updates: List[Any]  # CRDT update operations