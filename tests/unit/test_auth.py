import pytest

from src.auth.models import UserRole
from src.auth.service import (
    AuthService,
    UserRegister,
    verify_password,
)
from src.core.exceptions import UnauthorizedError


@pytest.mark.asyncio
async def test_user_registration_and_authentication(db_session):
    svc = AuthService(db_session)

    # Register
    user = await svc.register_user(
        UserRegister(
            email="solar.buyer@example.com",
            password="SecureSolarPassword123!",
            role=UserRole.BUYER,
            full_name="Arun Sharma",
            company_name="Sharma Green Energy",
        )
    )
    assert user.id is not None
    assert user.email == "solar.buyer@example.com"
    assert verify_password("SecureSolarPassword123!", user.hashed_password) is True

    # Authenticate
    auth_user, tokens = await svc.authenticate_user(email="solar.buyer@example.com", password="SecureSolarPassword123!")
    assert auth_user.id == user.id
    assert tokens.access_token is not None
    assert tokens.token_type == "bearer"

    # Incorrect password
    with pytest.raises(UnauthorizedError):
        await svc.authenticate_user(email="solar.buyer@example.com", password="WrongPassword!")


@pytest.mark.asyncio
async def test_duplicate_registration_rejected(db_session):
    svc = AuthService(db_session)
    data = UserRegister(
        email="seller@example.com",
        password="PassWord123!",
        role=UserRole.SELLER,
        full_name="Rajesh Patel",
    )
    await svc.register_user(data)

    with pytest.raises(UnauthorizedError) as exc:
        await svc.register_user(data)
    assert "already exists" in str(exc.value)
