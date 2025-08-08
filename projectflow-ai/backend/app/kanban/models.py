from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class KanbanBoard(Base):
    __tablename__ = "kanban_boards"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    project = relationship("Project", back_populates="boards")
    columns = relationship("KanbanColumn", back_populates="board", cascade="all, delete-orphan")


class KanbanColumn(Base):
    __tablename__ = "kanban_columns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    board_id = Column(Integer, ForeignKey("kanban_boards.id"), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    color = Column(String, nullable=True)  # hex color
    wip_limit = Column(Integer, nullable=True)  # work-in-progress limit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    board = relationship("KanbanBoard", back_populates="columns")
    cards = relationship("KanbanCard", back_populates="column", cascade="all, delete-orphan")


class KanbanCard(Base):
    __tablename__ = "kanban_cards"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    column_id = Column(Integer, ForeignKey("kanban_columns.id"), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    
    # Card metadata
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    priority = Column(String, default="medium")  # low, medium, high, urgent
    labels = Column(JSON, default=list)  # list of string labels
    due_date = Column(DateTime(timezone=True), nullable=True)
    
    # AI-related fields
    ai_agent = Column(String, nullable=True)  # which AI agent is assigned
    ai_status = Column(String, default="idle")  # idle, processing, completed, error
    ai_session_id = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    column = relationship("KanbanColumn", back_populates="cards")
    assignee = relationship("User")


# CRDT-related tables for Phase 2
class CRDTDoc(Base):
    __tablename__ = "crdt_docs"

    doc_id = Column(String, primary_key=True)  # UUID as string
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    doc_type = Column(String, nullable=False)  # 'board', 'card', etc.
    entity_id = Column(Integer, nullable=True)  # references the actual entity
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project")
    updates = relationship("CRDTUpdate", back_populates="doc", cascade="all, delete-orphan")


class CRDTUpdate(Base):
    __tablename__ = "crdt_updates"

    id = Column(Integer, primary_key=True, index=True)
    doc_id = Column(String, ForeignKey("crdt_docs.doc_id"), nullable=False)
    client_id = Column(String, nullable=False)
    seq = Column(Integer, nullable=False)
    update = Column(JSON, nullable=False)  # JSONB in Postgres
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    doc = relationship("CRDTDoc", back_populates="updates")
    
    # Unique constraint per doc + client + sequence
    __table_args__ = (
        {"schema": None},
    )