import pytest

from g2.infrastructure.database import AppDatabase


@pytest.fixture
def db() -> AppDatabase:
    """Create an in-memory database for testing."""
    app_db = AppDatabase()
    app_db._init_test()
    return app_db
