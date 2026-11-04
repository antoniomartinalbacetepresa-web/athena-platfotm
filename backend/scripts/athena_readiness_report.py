from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.athena_readiness_service import build_readiness_report


def build_report(
    *,
    database: AthenaDatabase | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    return build_readiness_report(
        database=database,
        as_of=as_of,
    )


def main() -> None:
    print(
        json.dumps(
            build_report(),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
