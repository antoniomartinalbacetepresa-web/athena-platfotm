from __future__ import annotations

from app.database.athena_database import AthenaDatabase
from app.repositories.normalized_data_repository import NormalizedDataRepository


def test_normalized_repository_initialize_creates_missing_database_parent(tmp_path) -> None:
    database_path = tmp_path / "nested" / "state" / "athena.db"
    assert database_path.parent.exists() is False

    repository = NormalizedDataRepository(AthenaDatabase(database_path))
    repository.initialize()

    assert database_path.parent.is_dir()
    assert database_path.is_file()
