from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_session
from app.main import app
from app.models import Student, Tutor

# Tests run on in-memory SQLite so they do not need Docker/Postgres.
TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(
        TEST_DATABASE_URL,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def tutor(session: AsyncSession) -> Tutor:
    tutor = Tutor(tg_id=100500, name="Anna")
    session.add(tutor)
    await session.commit()
    await session.refresh(tutor)
    return tutor


@pytest_asyncio.fixture
async def other_tutor(session: AsyncSession) -> Tutor:
    tutor = Tutor(tg_id=900900, name="Boris")
    session.add(tutor)
    await session.commit()
    await session.refresh(tutor)
    return tutor


@pytest_asyncio.fixture
async def student(session: AsyncSession, tutor: Tutor) -> Student:
    student = Student(tutor_id=tutor.id, name="Petya", price=Decimal("1500.00"))
    session.add(student)
    await session.commit()
    await session.refresh(student)
    return student
