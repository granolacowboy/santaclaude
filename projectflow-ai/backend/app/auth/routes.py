from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth import schemas
from app.auth.service import AuthService

router = APIRouter()
security = HTTPBearer()


@router.post("/login", response_model=schemas.Token)
async def login_for_access_token(
    email: str,
    password: str, 
    db: Session = Depends(get_db)
):
    """Login with email and password"""
    auth_service = AuthService(db)
    token = await auth_service.authenticate_user(email, password)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


@router.post("/register", response_model=schemas.User)
async def register_user(
    user: schemas.UserCreate,
    db: Session = Depends(get_db)
):
    """Register a new user"""
    auth_service = AuthService(db)
    try:
        return await auth_service.create_user(user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me", response_model=schemas.User)
async def get_current_user(
    token: str = Depends(security),
    db: Session = Depends(get_db)
):
    """Get current authenticated user"""
    auth_service = AuthService(db)
    user = await auth_service.get_current_user(token.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.get("/github/login")
async def github_login():
    """Initialize GitHub OAuth flow"""
    auth_service = AuthService(None)
    auth_url = await auth_service.get_github_auth_url()
    return {"auth_url": auth_url}


@router.post("/github/callback", response_model=schemas.Token) 
async def github_callback(
    callback: schemas.OAuthCallbackRequest,
    db: Session = Depends(get_db)
):
    """Handle GitHub OAuth callback"""
    auth_service = AuthService(db)
    try:
        token = await auth_service.handle_github_callback(callback.code, callback.state)
        return token
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))