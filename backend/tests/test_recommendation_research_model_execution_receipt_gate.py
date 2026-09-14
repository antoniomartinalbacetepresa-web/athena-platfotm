"""Gate regressions only; synthetic fixtures are not production OOS evidence."""

import pytest

from app.api import recommendation_research_forecast_evaluation as api


class _ReceiptRepositorySpy:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_by_specification_hash(
        self,
        *,
        specification_hash: str,
        specification_record: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append((specification_hash, specification_record))
        if self.error is not None:
            raise self.error
        return {"receipt_hash": "a" * 64, "artifact": {}}


def _record(version: str) -> dict[str, object]:
    return {
        "specification_hash": "b" * 64,
        "artifact": {"artifactVersion": version},
    }


def test_v3_gate_requires_persisted_execution_receipt(monkeypatch):
    repository = _ReceiptRepositorySpy()
    monkeypatch.setattr(api, "model_execution_receipt_repository", repository)
    record = _record("research-evaluation-specification-v3")

    api._verify_model_execution_receipt_if_required(record)

    assert repository.calls == [("b" * 64, record)]


def test_v3_gate_fails_closed_when_receipt_is_missing(monkeypatch):
    repository = _ReceiptRepositorySpy(
        error=ValueError("La evaluation specification no tiene model execution receipt persistido.")
    )
    monkeypatch.setattr(api, "model_execution_receipt_repository", repository)

    with pytest.raises(ValueError, match="no tiene model execution receipt"):
        api._verify_model_execution_receipt_if_required(
            _record("research-evaluation-specification-v3")
        )


@pytest.mark.parametrize(
    "version",
    ["research-evaluation-specification-v1", "research-evaluation-specification-v2"],
)
def test_legacy_v1_v2_remain_compatible_without_execution_receipt(monkeypatch, version):
    repository = _ReceiptRepositorySpy(
        error=AssertionError("legacy specifications must not query receipt storage")
    )
    monkeypatch.setattr(api, "model_execution_receipt_repository", repository)

    api._verify_model_execution_receipt_if_required(_record(version))

    assert repository.calls == []


def test_gate_rejects_malformed_persisted_specification(monkeypatch):
    monkeypatch.setattr(api, "model_execution_receipt_repository", _ReceiptRepositorySpy())
    with pytest.raises(ValueError, match="carece de artifact válido"):
        api._verify_model_execution_receipt_if_required(
            {"specification_hash": "b" * 64, "artifact": None}
        )
