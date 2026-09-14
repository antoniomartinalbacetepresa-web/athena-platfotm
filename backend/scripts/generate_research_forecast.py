"""Manual internal research generation; no HTTP-selected executable runner."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_research_executed_forecast_store_service import RecommendationResearchExecutedForecastStoreService
from app.services.recommendation_research_model_executor_service import RecommendationResearchModelExecutorService
from app.services.research_linear_total_return_runner import ResearchLinearTotalReturnRunner


def build_parser():
    parser = argparse.ArgumentParser(description="Generación manual de research v3, sin promoción ni trading.")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--template", type=Path)
    operation.add_argument("--recover-specification-hash", help="Recupera registros originales sin generar otra previsión.")
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--artifact-sha256", required=True)
    return parser


def _read_limited(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if not 0 < len(value) <= limit:
        raise ValueError("Archivo vacío o demasiado grande")
    return value


def run(args, *, store=None):
    pin = args.artifact_sha256
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise ValueError("SHA-256 explícito obligatorio")
    raw = _read_limited(args.model, 10_000_000)
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError("El modelo no coincide con el pin")
    recovery = getattr(args, "recover_specification_hash", None)
    if recovery is not None and not re.fullmatch(r"[0-9a-f]{64}", recovery):
        raise ValueError("Specification hash inválido")
    template = None if recovery is not None else json.loads(
        _read_limited(args.template, 1_000_000), object_pairs_hook=ResearchLinearTotalReturnRunner._unique)
    if store is None:
        store = RecommendationResearchExecutedForecastStoreService(
            database=AthenaDatabase(),
            executor=RecommendationResearchModelExecutorService(runner=ResearchLinearTotalReturnRunner()),
        )
    if recovery is not None:
        # Missing evidence fails closed. Never fall back to generate_and_persist.
        return store.recover_persisted(specification_hash=recovery, model_bytes=raw,
                                      pinned_artifact_hash=pin)
    return store.generate_and_persist(specification_template=template, model_bytes=raw,
                                     pinned_artifact_hash=pin)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        serialized = json.dumps(run(args), ensure_ascii=False, sort_keys=True, allow_nan=False)
    except Exception:
        parser.exit(1, "No se pudo verificar la generación; no se concede autoridad productiva.\n")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
