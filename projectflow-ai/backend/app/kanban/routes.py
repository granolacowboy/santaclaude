from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.service import AuthService
from app.projects.service import ProjectService
from app.kanban import schemas
from app.kanban.service import KanbanService

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


# Board routes
@router.get("/boards/{board_id}", response_model=schemas.KanbanBoard)
async def get_board(
    board_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a Kanban board with all columns and cards"""
    kanban_service = KanbanService(db)
    project_service = ProjectService(db)
    
    board = await kanban_service.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    # Check project access
    project_role = project_service._check_project_permission(board.project_id, current_user.id)
    if not project_role:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return board


@router.post("/boards", response_model=schemas.KanbanBoard)
async def create_board(
    board: schemas.KanbanBoardCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new Kanban board"""
    project_service = ProjectService(db)
    
    # Check project access
    project_role = project_service._check_project_permission(board.project_id, current_user.id)
    can_edit, _ = project_service._get_user_role_permissions(project_role)
    
    if not can_edit:
        raise HTTPException(status_code=403, detail="Access denied")
    
    kanban_service = KanbanService(db)
    return await kanban_service.create_board(board)


# Column routes
@router.post("/columns", response_model=schemas.KanbanColumn)
async def create_column(
    column: schemas.KanbanColumnCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new column"""
    kanban_service = KanbanService(db)
    project_service = ProjectService(db)
    
    # Get board to check project access
    board = await kanban_service.get_board(column.board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    project_role = project_service._check_project_permission(board.project_id, current_user.id)
    can_edit, _ = project_service._get_user_role_permissions(project_role)
    
    if not can_edit:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return await kanban_service.create_column(column)


@router.put("/columns/{column_id}", response_model=schemas.KanbanColumn)
async def update_column(
    column_id: int,
    column_update: schemas.KanbanColumnUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a column"""
    kanban_service = KanbanService(db)
    project_service = ProjectService(db)
    
    # Check access through board
    column = await kanban_service.get_column(column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")
    
    board = await kanban_service.get_board(column.board_id)
    project_role = project_service._check_project_permission(board.project_id, current_user.id)
    can_edit, _ = project_service._get_user_role_permissions(project_role)
    
    if not can_edit:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return await kanban_service.update_column(column_id, column_update)


# Card routes
@router.post("/cards", response_model=schemas.KanbanCard)
async def create_card(
    card: schemas.KanbanCardCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new card"""
    kanban_service = KanbanService(db)
    project_service = ProjectService(db)
    
    # Check access through column -> board -> project
    column = await kanban_service.get_column(card.column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")
    
    board = await kanban_service.get_board(column.board_id)
    project_role = project_service._check_project_permission(board.project_id, current_user.id)
    can_edit, _ = project_service._get_user_role_permissions(project_role)
    
    if not can_edit:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return await kanban_service.create_card(card)


@router.put("/cards/{card_id}", response_model=schemas.KanbanCard)
async def update_card(
    card_id: int,
    card_update: schemas.KanbanCardUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a card"""
    kanban_service = KanbanService(db)
    project_service = ProjectService(db)
    
    # Check access
    card = await kanban_service.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    column = await kanban_service.get_column(card.column_id)
    board = await kanban_service.get_board(column.board_id)
    project_role = project_service._check_project_permission(board.project_id, current_user.id)
    can_edit, _ = project_service._get_user_role_permissions(project_role)
    
    if not can_edit:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return await kanban_service.update_card(card_id, card_update)


@router.post("/cards/move")
async def move_card(
    move_request: schemas.CardMoveRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Move a card to a different column/position"""
    kanban_service = KanbanService(db)
    project_service = ProjectService(db)
    
    # Check access on both source and target
    card = await kanban_service.get_card(move_request.card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    target_column = await kanban_service.get_column(move_request.target_column_id)
    if not target_column:
        raise HTTPException(status_code=404, detail="Target column not found")
    
    # Verify both columns are in accessible boards
    source_column = await kanban_service.get_column(card.column_id)
    source_board = await kanban_service.get_board(source_column.board_id)
    target_board = await kanban_service.get_board(target_column.board_id)
    
    for board in [source_board, target_board]:
        project_role = project_service._check_project_permission(board.project_id, current_user.id)
        can_edit, _ = project_service._get_user_role_permissions(project_role)
        if not can_edit:
            raise HTTPException(status_code=403, detail="Access denied")
    
    await kanban_service.move_card(move_request)
    return {"message": "Card moved successfully"}


@router.delete("/cards/{card_id}")
async def delete_card(
    card_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a card"""
    kanban_service = KanbanService(db)
    project_service = ProjectService(db)
    
    # Check access
    card = await kanban_service.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    column = await kanban_service.get_column(card.column_id)
    board = await kanban_service.get_board(column.board_id)
    project_role = project_service._check_project_permission(board.project_id, current_user.id)
    can_edit, _ = project_service._get_user_role_permissions(project_role)
    
    if not can_edit:
        raise HTTPException(status_code=403, detail="Access denied")
    
    await kanban_service.delete_card(card_id)
    return {"message": "Card deleted successfully"}