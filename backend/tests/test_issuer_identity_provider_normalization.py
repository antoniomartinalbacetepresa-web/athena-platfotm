from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.issuer_identity_repository import IssuerIdentityRepository


def test_external_provider_case_variants_reuse_same_canonical_issuer(
    tmp_path: Path,
) -> None:
    repository = IssuerIdentityRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )

    first = repository.upsert_external_issuer(
        source_provider="SEC_EDGAR",
        external_id="0000320193",
        canonical_name="Apple Inc.",
        evidence_confidence=0.95,
    )
    second = repository.upsert_external_issuer(
        source_provider=" sec_edgar ",
        external_id="0000320193",
        canonical_name="Apple Inc.",
        evidence_confidence=0.98,
        domicile_country="United States",
        region_key="america",
    )

    assert first == second
    assert repository.list_external_ids(first) == [
        {
            "source_provider": "sec_edgar",
            "external_id": "0000320193",
            "evidence_confidence": 0.98,
        }
    ]
