from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, StaticPool

from src.core.config import get_settings

settings = get_settings()

# Naming convention for foreign keys and constraints
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)


class Base(DeclarativeBase):
    metadata = metadata


# Engine initialization
is_sqlite = settings.DATABASE_URL.startswith("sqlite")
engine_kwargs: dict = {
    "echo": settings.DEBUG,
    "future": True,
}

if is_sqlite:
    if ":memory:" in settings.DATABASE_URL:
        engine_kwargs["poolclass"] = StaticPool
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 10

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing a transactional async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
