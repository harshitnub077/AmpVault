import datetime

import pytest

from src.auth.dependencies import get_current_user, require_roles
from src.auth.models import UserRole
from src.auth.service import AuthService, UserRegister, create_token
from src.core.exceptions import UnauthorizedError


@pytest.mark.asyncio
async def test_auth_dependencies_validation(db_session):
    auth_svc = AuthService(db_session)
    user = await auth_svc.register_user(
        UserRegister(
            email="dep.test@example.com",
            password="Password123!",
            role=UserRole.SELLER,
            full_name="Seller One",
        )
    )

    # 1. Missing header
    with pytest.raises(UnauthorizedError) as exc:
        await get_current_user(authorization=None, db=db_session)
    assert "Missing or malformed" in str(exc.value)

    # 2. Malformed header
    with pytest.raises(UnauthorizedError):
        await get_current_user(authorization="Basic 12345", db=db_session)

    # 3. Invalid token
    with pytest.raises(UnauthorizedError):
        await get_current_user(authorization="Bearer invalid.token.value", db=db_session)

    # 4. Valid token
    token = create_token(user.id, user.role.value, datetime.timedelta(minutes=15))
    fetched_user = await get_current_user(authorization=f"Bearer {token}", db=db_session)
    assert fetched_user.id == user.id

    # 5. Require roles dependency
    seller_checker = require_roles(UserRole.SELLER, UserRole.ADMIN)
    checked_user = await seller_checker(user=fetched_user)
    assert checked_user.id == user.id

    buyer_checker = require_roles(UserRole.BUYER)
    with pytest.raises(UnauthorizedError) as exc_role:
        await buyer_checker(user=fetched_user)
    assert "Access denied" in str(exc_role.value)
