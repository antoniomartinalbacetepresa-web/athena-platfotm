from __future__ import annotations

from typing import Any

from app.models.normalized_data import DataProvenance, NormalizedDatum


class SecNormalizationService:
    """Normalize selected SEC Company Facts observations into ATHENA data."""

    _SOURCE_ID = "sec_edgar_xbrl"

    def normalize_company_fact(
        self,
        *,
        cik: str,
        taxonomy: str,
        concept: str,
        unit: str,
        observation: dict[str, Any],
        quality_score: float = 100.0,
    ) -> NormalizedDatum:
        value = observation.get("val")
        if not isinstance(value, (int, float)):
            raise ValueError("SEC observation must contain a numeric val.")

        filed = self._optional_text(observation.get("filed"))
        effective_at = self._optional_text(observation.get("end"))
        accession = self._optional_text(observation.get("accn"))
        form = self._optional_text(observation.get("form"))
        frame = self._optional_text(observation.get("frame"))

        normalized_cik = "".join(character for character in str(cik) if character.isdigit())
        if not normalized_cik:
            raise ValueError("CIK is required.")

        normalized_metric = self.metric_identifier(taxonomy=taxonomy, concept=concept)
        raw_identifier = ":".join(part for part in (taxonomy.strip(), concept.strip(), unit.strip()) if part)

        version_parts = [part for part in (form, accession, frame) if part]
        version = "|".join(version_parts) if version_parts else None

        return NormalizedDatum(
            metric=normalized_metric,
            value=value,
            data_kind="fact",
            provenance=DataProvenance.now(
                source_id=self._SOURCE_ID,
                effective_at=effective_at,
                published_at=filed,
                source_timestamp=filed,
                version=version,
                raw_identifier=raw_identifier,
                normalized_identifier=normalized_metric,
                source_url=(
                    f"https://data.sec.gov/api/xbrl/companyfacts/CIK{normalized_cik.zfill(10)}.json"
                ),
            ),
            unit=unit.strip() or None,
            entity_id=f"sec-cik:{normalized_cik.zfill(10)}",
            quality_score=quality_score,
        )

    def normalize_concept_units(
        self,
        *,
        cik: str,
        taxonomy: str,
        concept: str,
        units: dict[str, list[dict[str, Any]]],
        quality_score: float = 100.0,
    ) -> list[NormalizedDatum]:
        result: list[NormalizedDatum] = []
        for unit, observations in units.items():
            for observation in observations:
                result.append(
                    self.normalize_company_fact(
                        cik=cik,
                        taxonomy=taxonomy,
                        concept=concept,
                        unit=unit,
                        observation=observation,
                        quality_score=quality_score,
                    )
                )
        return result

    @staticmethod
    def metric_identifier(*, taxonomy: str, concept: str) -> str:
        normalized_taxonomy = taxonomy.strip().lower().replace(" ", "_")
        normalized_concept = concept.strip().lower().replace(" ", "_")
        if not normalized_taxonomy or not normalized_concept:
            raise ValueError("taxonomy and concept are required.")
        return f"fundamental.{normalized_taxonomy}.{normalized_concept}"

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
