from __future__ import annotations

from pathlib import Path

# Keep the complete historical database regression suite while making its
# version assertions track the canonical schema constant. The source is kept
# separately so no pre-v5 regression coverage is dropped during the migration.
_source_path = Path(__file__).with_name("athena_database_regressions.py")
_source = _source_path.read_text(encoding="utf-8-sig")
_source = _source.replace(
    'assert version_row["value"] == "4"',
    'assert version_row["value"] == str(AthenaDatabase.SCHEMA_VERSION)',
)
exec(compile(_source, str(_source_path), "exec"), globals())
