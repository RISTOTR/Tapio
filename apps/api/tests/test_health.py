from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from apps.api.app.core.database import get_session
from apps.api.app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health_success_and_database_failure() -> None:
    session = MagicMock(spec=Session)

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "database": "ok"}
            session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("private"))
            response = await client.get("/health")
            assert response.status_code == 503
            assert response.json() == {"detail": "Database unavailable"}
    finally:
        app.dependency_overrides.clear()
