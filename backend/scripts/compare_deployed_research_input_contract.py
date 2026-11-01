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
from app.repositories.recommendation_athena_synthesis_repository import RecommendationAthenaSynthesisRepository
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


def fetch_deployed_synthesis(
    *, origin: str, cycle_hash: str, allow_loopback_http: bool = False,
) -> dict[str, object]:
    if not _SHA.fullmatch(cycle_hash):
        raise ValueError("cycle_hash debe ser SHA-256 hexadecimal en minúsculas.")
    base = _validated_origin(origin, allow_loopback_http=allow_loopback_http)
    request = Request(
        base + _ENDPOINT.replace("/input-contract", "").format(cycle_hash=cycle_hash),
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
        raise ValueError("El backend no devolvió una síntesis persistida canónica.")
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
    # These fields are outside the fingerprint and must be checked explicitly:
    # otherwise a deployed response could claim partial coverage while matching
    # the same evidence hashes, or advertise authority the gate never grants.
    required_categories = [
        category for category in ("news", "investors")
        if expected[f"{category}SynthesisHash"] is not None
    ]
    if (
        deployed_contract.get("requiredCoverage") != "all_cycle_radar_evidence"
        or deployed_contract.get("canonicalCategorySynthesesRequired") != required_categories
    ):
        raise ValueError("El despliegue no declara cobertura canónica completa.")
    if (
        deployed_contract.get("advisoryStatus") != "no_advice"
        or deployed_contract.get("recommendationInfluence") is not False
        or deployed_contract.get("automaticTrading") is not False
        or any(
            deployed_contract.get(field) is not False
            for field in (
                "modelExecutionVerified", "productionEligible",
                "sourceAuthenticityIndependentlyVerified",
            ) if field in deployed_contract
        )
    ):
        raise ValueError("El despliegue no conserva los límites de autoridad.")
    for category, hash_field, provenance_field in (
        ("news", "newsSynthesisHash", "newsProvenance"),
        ("investors", "investorsSynthesisHash", "investorsProvenance"),
    ):
        required = expected[hash_field] is not None
        if (provenance_field in deployed_contract) != required:
            raise ValueError(f"Falta o sobra provenance {category}.")
        if required:
            provenance = deployed_contract[provenance_field]
            digest = snapshot_report.get(f"{category}ProvenanceSha256")
            if (
                not isinstance(provenance, dict)
                or not isinstance(digest, str)
                or not _SHA.fullmatch(digest)
                or _canonical_hash(provenance) != digest
            ):
                raise ValueError(
                    f"La provenance {category} desplegada difiere del snapshot canónico."
                )
        elif snapshot_report.get(f"{category}ProvenanceSha256") is not None:
            raise ValueError(f"El snapshot conserva provenance {category} inesperada.")
    return {
        "status": "snapshot_deployed_input_contract_matched",
        "cycleHash": expected["cycleHash"],
        "inputFingerprint": expected["inputFingerprint"],
        "snapshotSha256": snapshot_report["snapshotSha256"],
        "athenaAlreadyPersistedInSnapshot": snapshot_report["athenaAlreadyPersisted"],
        "snapshotReadyForNewLocalDraft": snapshot_report["readyForNewLocalDraft"],
        # An input-contract GET cannot prove the deployed database has no ATHENA
        # synthesis: another process may have persisted one after the snapshot.
        "readyForNewLocalDraft": False,
        "deployedAthenaAbsenceVerified": False,
        "deployedPersistenceVerified": False,
        "modelExecutionVerified": False,
        "sourceAuthenticityIndependentlyVerified": False,
        "productionEligible": False,
        "automaticTrading": False,
        "interpretation": "read_only_point_in_time_match_not_authorization_to_persist_or_trade",
    }



def compare_persisted_readback(
    snapshot_report: dict[str, object],
    deployed_contract: dict[str, object],
    deployed_readback: dict[str, object],
) -> dict[str, object]:
    """Prove that a deployed GET serves the exact ATHENA artifact in the snapshot.

    This is a read-only artifact-consistency check, not proof of model execution
    or source authenticity. It deliberately cannot attest a later database state.
    """
    compare_contract(snapshot_report, deployed_contract)
    if (
        snapshot_report.get("athenaAlreadyPersisted") is not True
        or snapshot_report.get("persistedAthenaIntegrityVerified") is not True
    ):
        raise ValueError("El snapshot no contiene ATHENA persistida verificada.")
    if not isinstance(deployed_readback, dict) or deployed_readback.get("artifactBindingVerified") is not True:
        raise ValueError("La respuesta ATHENA desplegada no confirma vinculación canónica.")
    synthesis = deployed_readback.get("synthesis")
    persistence = deployed_readback.get("persistence")
    provenance = deployed_readback.get("provenance")
    if not isinstance(synthesis, dict) or not isinstance(persistence, dict) or not isinstance(provenance, dict):
        raise ValueError("La respuesta ATHENA desplegada está incompleta.")
    expected_provenance = {"inputFingerprint": snapshot_report["snapshotDerivedInputFingerprint"]}
    for category in ("news", "investors"):
        binding = deployed_contract.get(f"{category}Provenance")
        if binding is not None:
            expected_provenance[category] = binding
    if provenance != expected_provenance:
        raise ValueError("La provenance ATHENA desplegada no coincide con el input canónico.")
    repo = RecommendationAthenaSynthesisRepository()
    package = repo.validate_package(
        cycle_hash=snapshot_report["cycleHash"],
        radar_hash=snapshot_report["radarHash"],
        news_synthesis_hash=snapshot_report["newsSynthesisHash"],
        synthesis_payload=synthesis,
    )
    synthesis_hash = _canonical_hash(package)
    if (
        synthesis_hash != snapshot_report.get("persistedAthenaSynthesisHash")
        or persistence.get("synthesisHash") != synthesis_hash
        or persistence.get("appendOnly") is not True
        or persistence.get("packageIntegrityVerified") is not True
        or persistence.get("cycleHash") != snapshot_report["cycleHash"]
        or persistence.get("radarHash") != snapshot_report["radarHash"]
        or persistence.get("newsSynthesisHash") != snapshot_report["newsSynthesisHash"]
        or persistence.get("investorsSynthesisHash") != snapshot_report["investorsSynthesisHash"]
    ):
        raise ValueError("La persistencia ATHENA desplegada no coincide con el snapshot.")
    if (
        synthesis.get("inputFingerprint") != snapshot_report["snapshotDerivedInputFingerprint"]
        or synthesis.get("outputFingerprint") != snapshot_report.get("persistedAthenaOutputFingerprint")
        or synthesis.get("investorsSynthesisHash") != snapshot_report["investorsSynthesisHash"]
        or synthesis.get("coveredCategories") != snapshot_report["categories"]
        or not isinstance(synthesis.get("evidenceIds"), list)
        or len(synthesis["evidenceIds"]) != snapshot_report["evidenceCount"]
        or _canonical_hash(sorted(synthesis["evidenceIds"])) != snapshot_report["evidenceIdsSha256"]
        or _utc(synthesis.get("inputAsOf"), "athena.inputAsOf") != _utc(snapshot_report["inputAsOf"], "snapshot.inputAsOf")
        or _utc(synthesis.get("generatedAt"), "athena.generatedAt") < _utc(snapshot_report["inputAsOf"], "snapshot.inputAsOf")
    ):
        raise ValueError("La síntesis ATHENA desplegada no coincide con el contrato canónico.")
    output_fields = (
        "modelProvider", "modelName", "modelVersion", "generatedAt",
        "summary", "rationale", "uncertainties", "evidenceIds",
    )
    if any(field not in synthesis for field in output_fields):
        raise ValueError("La síntesis ATHENA desplegada carece de campos de salida.")
    expected_output = _canonical_hash({
        "inputFingerprint": snapshot_report["snapshotDerivedInputFingerprint"],
        **{field: synthesis[field] for field in output_fields},
        "investorsSynthesisHash": snapshot_report["investorsSynthesisHash"],
    })
    if synthesis.get("outputFingerprint") != expected_output:
        raise ValueError("El outputFingerprint ATHENA desplegado no es canónico.")
    return {
        "status": "snapshot_deployed_athena_readback_matched",
        "cycleHash": snapshot_report["cycleHash"],
        "snapshotSha256": snapshot_report["snapshotSha256"],
        "synthesisHash": synthesis_hash,
        "deployedPersistenceVerified": True,
        "deployedAthenaAbsenceVerified": False,
        "readyForNewLocalDraft": False,
        "modelExecutionVerified": False,
        "sourceAuthenticityIndependentlyVerified": False,
        "productionEligible": False,
        "automaticTrading": False,
        "interpretation": "read_only_exact_artifact_match_not_model_execution_or_production_authority",
    }



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--cycle-hash", required=True)
    parser.add_argument("--backend-origin", required=True)
    parser.add_argument("--allow-loopback-http", action="store_true")
    parser.add_argument("--verify-persisted-readback", action="store_true",
                        help="Require exact readback of an ATHENA artifact already present in the trusted snapshot.")
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
        if args.verify_persisted_readback:
            if report["athenaAlreadyPersisted"] is not True:
                raise ValueError("El snapshot no contiene ATHENA persistida para comparar.")
            readback = fetch_deployed_synthesis(
                origin=args.backend_origin, cycle_hash=args.cycle_hash,
                allow_loopback_http=args.allow_loopback_http,
            )
            result = compare_persisted_readback(report, deployed, readback)
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
