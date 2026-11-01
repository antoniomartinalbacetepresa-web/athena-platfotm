"""Read-only gate: compare a trusted SQLite snapshot to the deployed ATHENA input contract.

No Ollama calls, database writes, model promotion or investment orders.
The deployed URL must be an explicitly supplied HTTPS origin; loopback HTTP
requires a separate development-only opt-in. Never pass credentials in URLs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.recommendation_athena_synthesis import _canonical_hash
from scripts.verify_persisted_research_cycle_snapshot import _SHA, _utc, verify

_MAX_RESPONSE_BYTES = 131072
_ENDPOINT = (
    "/api/v1/recommendations/professional-research/research-cycle/"
    "{cycle_hash}/athena-synthesis/input-contract"
)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("El endpoint desplegado no debe redirigir.")


def _validated_origin(origin: str, *, allow_loopback_http: bool) -> str:
    parsed = urlsplit(origin)
    if (
        not parsed.hostname or parsed.username is not None or parsed.password is not None
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
    ):
        raise ValueError("Indica solo el origen del backend, sin ruta, credenciales ni parámetros.")
    if parsed.scheme == "https":
        return "https://" + parsed.netloc
    if (
        parsed.scheme == "http" and allow_loopback_http
        and parsed.hostname == "127.0.0.1"
    ):
        return "http://" + parsed.netloc
    raise ValueError("El backend debe usar HTTPS; HTTP solo se admite en 127.0.0.1 con opt-in.")


def fetch_deployed_contract(
    *, origin: str, cycle_hash: str, allow_loopback_http: bool = False,
) -> dict[str, object]:
    if not _SHA.fullmatch(cycle_hash):
        raise ValueError("cycle_hash debe ser SHA-256 hexadecimal en minúsculas.")
    base = _validated_origin(origin, allow_loopback_http=allow_loopback_http)
    request = Request(
        base + _ENDPOINT.format(cycle_hash=cycle_hash),
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with build_opener(ProxyHandler({}), _RejectRedirects()).open(
            request, timeout=15
        ) as response:
            if response.status != 200:
                raise ValueError("El backend no devolvió HTTP 200.")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        # Never print URLs, response bodies, headers, or credentials.
        raise ValueError("No se pudo obtener el contrato del backend desplegado.") from exc
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("La respuesta del backend supera el límite permitido.")
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("El backend devolvió JSON inválido.") from exc
    if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
        raise ValueError("El backend no devolvió un contrato canónico.")
    return envelope["data"]


def compare_contract(
    snapshot_report: dict[str, object], deployed_contract: dict[str, object],
) -> dict[str, object]:
    """Fail closed on any mismatch. A match is NOT permission to persist a draft."""
    if not isinstance(snapshot_report, dict) or not isinstance(deployed_contract, dict):
        raise ValueError("Se requieren contratos de snapshot y despliegue válidos.")
    if snapshot_report.get("status") != "canonical_snapshot_dependencies_verified":
        raise ValueError("El snapshot no está verificado canónicamente.")
    expected = {
        "cycleHash": snapshot_report["cycleHash"],
        "radarHash": snapshot_report["radarHash"],
        "newsSynthesisHash": snapshot_report["newsSynthesisHash"],
        "investorsSynthesisHash": snapshot_report["investorsSynthesisHash"],
        "inputFingerprint": snapshot_report["snapshotDerivedInputFingerprint"],
    }
    for field, value in expected.items():
        if deployed_contract.get(field) != value:
            raise ValueError(f"El contrato desplegado difiere del snapshot en {field}.")
    try:
        if _utc(deployed_contract.get("inputAsOf"), "inputAsOf") != _utc(
            snapshot_report.get("inputAsOf"), "snapshot.inputAsOf"
        ):
            raise ValueError("El corte PIT difiere entre snapshot y despliegue.")
    except (TypeError, AttributeError) as exc:
        raise ValueError("El corte PIT del despliegue es inválido.") from exc
    ids = deployed_contract.get("evidenceIds")
    categories = deployed_contract.get("coveredCategories")
    if (
        not isinstance(ids, list)
        or not all(isinstance(item, str) and item for item in ids)
        or len(ids) != len(set(ids))
        or len(ids) != snapshot_report.get("evidenceCount")
        or _canonical_hash(sorted(ids)) != snapshot_report.get("evidenceIdsSha256")
        or not isinstance(categories, list)
        or not all(isinstance(item, str) and item for item in categories)
        or len(categories) != len(set(categories))
        or sorted(categories) != snapshot_report.get("categories")
    ):
        raise ValueError("Las evidencias o categorías del despliegue difieren del snapshot.")
    if (
        deployed_contract.get("advisoryStatus") != "no_advice"
        or deployed_contract.get("recommendationInfluence") is not False
        or deployed_contract.get("automaticTrading") is not False
    ):
        raise ValueError("El despliegue no conserva los límites de autoridad.")
    for category, hash_field, provenance_field in (
        ("news", "newsSynthesisHash", "newsProvenance"),
        ("investors", "investorsSynthesisHash", "investorsProvenance"),
    ):
        required = expected[hash_field] is not None
        if (provenance_field in deployed_contract) != required:
            raise ValueError(f"Falta o sobra provenance {category}.")
    return {
        "status": "snapshot_deployed_input_contract_matched",
        "cycleHash": expected["cycleHash"],
        "inputFingerprint": expected["inputFingerprint"],
        "snapshotSha256": snapshot_report["snapshotSha256"],
        "athenaAlreadyPersistedInSnapshot": snapshot_report["athenaAlreadyPersisted"],
        "readyForNewLocalDraft": snapshot_report["readyForNewLocalDraft"],
        "deployedPersistenceVerified": False,
        "modelExecutionVerified": False,
        "sourceAuthenticityIndependentlyVerified": False,
        "productionEligible": False,
        "automaticTrading": False,
        "interpretation": "read_only_point_in_time_match_not_authorization_to_persist_or_trade",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--cycle-hash", required=True)
    parser.add_argument("--backend-origin", required=True)
    parser.add_argument("--allow-loopback-http", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = verify(
            args.snapshot, expected_sha256=args.expected_sha256,
            cycle_hash=args.cycle_hash,
        )
        deployed = fetch_deployed_contract(
            origin=args.backend_origin, cycle_hash=args.cycle_hash,
            allow_loopback_http=args.allow_loopback_http,
        )
        result = compare_contract(report, deployed)
    except (ValueError, OSError) as exc:
        # Do not print potentially sensitive values from network responses.
        print(json.dumps({"status": "blocked", "reason": type(exc).__name__,
                          "detail": str(exc) if isinstance(exc, ValueError) else "Error de lectura."},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
