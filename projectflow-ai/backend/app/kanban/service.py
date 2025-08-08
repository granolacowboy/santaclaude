from typing import Optional, List
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func

from app.kanban.models import KanbanBoard, KanbanColumn, KanbanCard
from app.kanban import schemas


class KanbanService:
    def __init__(self, db: Session):
        self.db = db
    
    # Board methods
    async def get_board(self, board_id: int) -> Optional[KanbanBoard]:
        """Get a board with all columns and cards"""
        return (
            self.db.query(KanbanBoard)
            .options(
                selectinload(KanbanBoard.columns)
                .selectinload(KanbanColumn.cards)
            )
            .filter(KanbanBoard.id == board_id)
            .first()
        )
    
    async def create_board(self, board_create: schemas.KanbanBoardCreate) -> KanbanBoard:
        """Create a new board with default columns"""
        db_board = KanbanBoard(**board_create.model_dump())
        
        self.db.add(db_board)
        self.db.commit()
        self.db.refresh(db_board)
        
        # Create default columns
        default_columns = [
            {"name": "To Do", "position": 0, "color": "#e2e8f0"},
            {"name": "In Progress", "position": 1, "color": "#3b82f6"},  
            {"name": "Review", "position": 2, "color": "#f59e0b"},
            {"name": "Done", "position": 3, "color": "#10b981"}
        ]
        
        for col_data in default_columns:
            column = KanbanColumn(
                board_id=db_board.id,
                **col_data
            )
            self.db.add(column)
        
        self.db.commit()
        
        # Reload board with columns
        return await self.get_board(db_board.id)
    
    async def update_board(
        self, 
        board_id: int, 
        board_update: schemas.KanbanBoardUpdate
    ) -> Optional[KanbanBoard]:
        """Update a board"""
        board = self.db.query(KanbanBoard).filter(KanbanBoard.id == board_id).first()
        if not board:
            return None
        
        update_data = board_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(board, field, value)
        
        self.db.commit()
        self.db.refresh(board)
        
        return board
    
    # Column methods
    async def get_column(self, column_id: int) -> Optional[KanbanColumn]:
        """Get a column"""
        return self.db.query(KanbanColumn).filter(KanbanColumn.id == column_id).first()
    
    async def create_column(self, column_create: schemas.KanbanColumnCreate) -> KanbanColumn:
        """Create a new column"""
        # If position not specified, add to end
        if column_create.position is None:
            max_position = (
                self.db.query(func.max(KanbanColumn.position))
                .filter(KanbanColumn.board_id == column_create.board_id)
                .scalar() or -1
            )
            position = max_position + 1
        else:
            position = column_create.position
        
        db_column = KanbanColumn(
            **column_create.model_dump(exclude={"position"}),
            position=position
        )
        
        self.db.add(db_column)
        self.db.commit()
        self.db.refresh(db_column)
        
        return db_column
    
    async def update_column(
        self, 
        column_id: int, 
        column_update: schemas.KanbanColumnUpdate
    ) -> Optional[KanbanColumn]:
        """Update a column"""
        column = self.db.query(KanbanColumn).filter(KanbanColumn.id == column_id).first()
        if not column:
            return None
        
        update_data = column_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(column, field, value)
        
        self.db.commit()
        self.db.refresh(column)
        
        return column
    
    # Card methods
    async def get_card(self, card_id: int) -> Optional[KanbanCard]:
        """Get a card"""
        return self.db.query(KanbanCard).filter(KanbanCard.id == card_id).first()
    
    async def create_card(self, card_create: schemas.KanbanCardCreate) -> KanbanCard:
        """Create a new card"""
        # Add to end of column
        max_position = (
            self.db.query(func.max(KanbanCard.position))
            .filter(KanbanCard.column_id == card_create.column_id)
            .scalar() or -1
        )
        
        db_card = KanbanCard(
            **card_create.model_dump(),
            position=max_position + 1
        )
        
        self.db.add(db_card)
        self.db.commit()
        self.db.refresh(db_card)
        
        return db_card
    
    async def update_card(
        self, 
        card_id: int, 
        card_update: schemas.KanbanCardUpdate
    ) -> Optional[KanbanCard]:
        """Update a card"""
        card = self.db.query(KanbanCard).filter(KanbanCard.id == card_id).first()
        if not card:
            return None
        
        update_data = card_update.model_dump(exclude_unset=True)
        
        # Handle column change (move between columns)
        if "column_id" in update_data:
            await self._handle_card_column_change(card, update_data["column_id"])
        
        for field, value in update_data.items():
            setattr(card, field, value)
        
        self.db.commit()
        self.db.refresh(card)
        
        return card
    
    async def move_card(self, move_request: schemas.CardMoveRequest):
        """Move a card to a specific position in a column"""
        card = await self.get_card(move_request.card_id)
        if not card:
            return
        
        old_column_id = card.column_id
        new_column_id = move_request.target_column_id
        new_position = move_request.target_position
        
        # Update positions in old column (if changed)
        if old_column_id != new_column_id:
            # Shift positions in old column
            self.db.query(KanbanCard).filter(
                KanbanCard.column_id == old_column_id,
                KanbanCard.position > card.position
            ).update({KanbanCard.position: KanbanCard.position - 1})
        
        # Update positions in new column
        self.db.query(KanbanCard).filter(
            KanbanCard.column_id == new_column_id,
            KanbanCard.position >= new_position,
            KanbanCard.id != card.id
        ).update({KanbanCard.position: KanbanCard.position + 1})
        
        # Update the card
        card.column_id = new_column_id
        card.position = new_position
        
        self.db.commit()
    
    async def delete_card(self, card_id: int) -> bool:
        """Delete a card"""
        card = self.db.query(KanbanCard).filter(KanbanCard.id == card_id).first()
        if not card:
            return False
        
        column_id = card.column_id
        position = card.position
        
        # Delete the card
        self.db.delete(card)
        
        # Shift remaining cards up
        self.db.query(KanbanCard).filter(
            KanbanCard.column_id == column_id,
            KanbanCard.position > position
        ).update({KanbanCard.position: KanbanCard.position - 1})
        
        self.db.commit()
        return True
    
    async def _handle_card_column_change(self, card: KanbanCard, new_column_id: int):
        """Handle repositioning when card moves between columns"""
        if card.column_id == new_column_id:
            return
        
        old_column_id = card.column_id
        old_position = card.position
        
        # Shift positions in old column
        self.db.query(KanbanCard).filter(
            KanbanCard.column_id == old_column_id,
            KanbanCard.position > old_position
        ).update({KanbanCard.position: KanbanCard.position - 1})
        
        # Add to end of new column
        max_position = (
            self.db.query(func.max(KanbanCard.position))
            .filter(KanbanCard.column_id == new_column_id)
            .scalar() or -1
        )
        
        card.position = max_position + 1