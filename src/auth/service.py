import datetime
import uuid

import bcrypt
import jwt
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User, UserRole
from src.core.config import get_settings
from src.core.exceptions import UnauthorizedError

settings = get_settings()


class UserRegister(BaseModel):
    email: EmailStr
    password: str
    role: UserRole
    full_name: str
    company_name: str | None = None
    gstin: str | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    role: UserRole
    full_name: str
    company_name: str | None
    gstin: str | None
    is_active: bool
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_token(user_id: str, role: str, expires_delta: datetime.timedelta) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register_user(self, data: UserRegister) -> User:
        stmt = select(User).where(User.email == data.email)
        res = await self.session.execute(stmt)
        if res.scalar_one_or_none():
            raise UnauthorizedError(f"User with email '{data.email}' already exists")

        user = User(
            id=str(uuid.uuid4()),
            email=data.email,
            hashed_password=hash_password(data.password),
            role=data.role,
            full_name=data.full_name,
            company_name=data.company_name,
            gstin=data.gstin,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def authenticate_user(self, email: str, password: str) -> tuple[User, TokenResponse]:
        stmt = select(User).where(User.email == email)
        res = await self.session.execute(stmt)
        user = res.scalar_one_or_none()
        if not user or not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password")
        if not user.is_active:
            raise UnauthorizedError("User account is inactive")

        access_token = create_token(
            user.id, user.role.value, datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        refresh_token = create_token(
            user.id, user.role.value, datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )

        tokens = TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
        return user, tokens
