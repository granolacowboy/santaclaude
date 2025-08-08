from datetime import datetime, timedelta
from typing import Optional
import secrets
import hashlib

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
import httpx

from app.core.config import get_settings
from app.auth.models import User, UserIdentity
from app.auth import schemas

settings = get_settings()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return pwd_context.verify(plain_password, hashed_password)
    
    def get_password_hash(self, password: str) -> str:
        """Hash a password"""
        return pwd_context.hash(password)
    
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None):
        """Create a JWT access token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
        return encoded_jwt
    
    def create_refresh_token(self, data: dict) -> str:
        """Create a JWT refresh token"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    
    async def authenticate_user(self, email: str, password: str) -> Optional[schemas.Token]:
        """Authenticate user with email and password"""
        user = self.db.query(User).filter(User.email == email).first()
        if not user or not user.hashed_password:
            return None
        if not self.verify_password(password, user.hashed_password):
            return None
        
        access_token = self.create_access_token(data={"sub": str(user.id)})
        refresh_token = self.create_refresh_token(data={"sub": str(user.id)})
        
        return schemas.Token(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
    
    async def create_user(self, user_create: schemas.UserCreate) -> User:
        """Create a new user"""
        # Check if user already exists
        existing_user = self.db.query(User).filter(User.email == user_create.email).first()
        if existing_user:
            raise ValueError("User with this email already exists")
        
        existing_username = self.db.query(User).filter(User.username == user_create.username).first()
        if existing_username:
            raise ValueError("Username already taken")
        
        # Create new user
        db_user = User(
            email=user_create.email,
            username=user_create.username,
            full_name=user_create.full_name,
            hashed_password=self.get_password_hash(user_create.password) if user_create.password else None,
            is_active=user_create.is_active
        )
        
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)
        
        return db_user
    
    async def get_current_user(self, token: str) -> Optional[User]:
        """Get current user from JWT token"""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id: str = payload.get("sub")
            if user_id is None:
                return None
        except JWTError:
            return None
        
        user = self.db.query(User).filter(User.id == int(user_id)).first()
        return user
    
    async def get_github_auth_url(self) -> str:
        """Generate GitHub OAuth authorization URL"""
        state = secrets.token_urlsafe(32)
        # In production, store state in Redis/session for verification
        
        params = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": "http://localhost:3000/auth/callback",
            "scope": "user:email read:user",
            "state": state,
        }
        
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"https://github.com/login/oauth/authorize?{query_string}"
    
    async def handle_github_callback(self, code: str, state: str) -> schemas.Token:
        """Handle GitHub OAuth callback and create/login user"""
        # Exchange code for access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                },
                headers={"Accept": "application/json"}
            )
            token_data = token_response.json()
            
            if "access_token" not in token_data:
                raise ValueError("Failed to get access token from GitHub")
            
            access_token = token_data["access_token"]
            
            # Get user info from GitHub
            user_response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            github_user = user_response.json()
            
            # Get primary email
            emails_response = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            emails = emails_response.json()
            primary_email = next((e["email"] for e in emails if e["primary"]), None)
            
            if not primary_email:
                raise ValueError("No primary email found in GitHub account")
        
        # Find or create user
        user = self.db.query(User).filter(User.email == primary_email).first()
        
        if not user:
            # Create new user from GitHub data
            user = User(
                email=primary_email,
                username=github_user["login"],
                full_name=github_user.get("name"),
                is_active=True
            )
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
        
        # Create or update identity
        identity = self.db.query(UserIdentity).filter(
            UserIdentity.user_id == user.id,
            UserIdentity.provider == "github"
        ).first()
        
        if not identity:
            identity = UserIdentity(
                user_id=user.id,
                provider="github",
                provider_user_id=str(github_user["id"]),
                provider_username=github_user["login"],
                access_token=access_token
            )
            self.db.add(identity)
        else:
            identity.access_token = access_token
            identity.provider_username = github_user["login"]
        
        self.db.commit()
        
        # Create JWT tokens
        access_token_jwt = self.create_access_token(data={"sub": str(user.id)})
        refresh_token_jwt = self.create_refresh_token(data={"sub": str(user.id)})
        
        return schemas.Token(
            access_token=access_token_jwt,
            refresh_token=refresh_token_jwt,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )