from collections.abc import Callable

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User, UserRole
from src.core.config import get_settings
from src.core.database import get_db
from src.core.exceptions import UnauthorizedError

settings = get_settings()


async def get_current_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate Bearer JWT and return current active user."""
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header")

    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise UnauthorizedError("Invalid token payload: missing subject")
    except jwt.PyJWTError as e:
        raise UnauthorizedError(f"JWT validation failed: {str(e)}")

    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or inactive")

    return user


def require_roles(*allowed_roles: UserRole) -> Callable:
    """Dependency factory enforcing RBAC for specific user roles."""

    async def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise UnauthorizedError(
                f"Access denied: user role '{user.role.value}' does not have required permissions [{', '.join(r.value for r in allowed_roles)}]"
            )
        return user

    return role_checker
