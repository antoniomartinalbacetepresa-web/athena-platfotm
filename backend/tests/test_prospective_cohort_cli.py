"""CLI regressions are synthetic software evidence, not production observations."""
import pytest

from scripts.prospective_cohort import build_parser, run
from scripts import prospective_cohort as cli


class Ledger:
    def register(self, **kwargs):
        return kwargs

    def get(self, **kwargs):
        return kwargs

    def coverage(self, **kwargs):
        return {**kwargs, "outcomeEvidenceVerified": False}


def test_register_forwards_all_selected_hashes_without_inventing_membership():
    args = build_parser().parse_args(["register", "--cohort-id", "cohort",
                                     "--specification-hash", "a" * 64,
                                     "--specification-hash", "b" * 64])
    assert run(args, service=Ledger())["specification_hashes"] == ["a" * 64, "b" * 64]


def test_show_requests_exact_existing_cohort():
    args = build_parser().parse_args(["show", "--cohort-id", "cohort"])
    assert run(args, service=Ledger()) == {"cohort_id": "cohort"}


def test_empty_coverage_is_explicit_and_does_not_claim_outcome_evidence():
    args = build_parser().parse_args(["coverage", "--cohort-id", "cohort"])
    result = run(args, service=Ledger())
    assert result["evaluated_specification_hashes"] == []
    assert result["outcomeEvidenceVerified"] is False


def test_ledger_failure_is_not_replaced_with_a_successful_result():
    class Broken(Ledger):
        def get(self, **kwargs):
            raise ValueError("Invalid selection")
    args = build_parser().parse_args(["show", "--cohort-id", "cohort"])
    with pytest.raises(ValueError):
        run(args, service=Broken())


def test_cli_emits_one_validated_json_result(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run", lambda args: {"automaticTrading": False})
    assert cli.main(["show", "--cohort-id", "cohort"]) == 0
    captured = capsys.readouterr()
    assert captured.out == '{"automaticTrading": false}\n'
    assert captured.err == ""


@pytest.mark.parametrize("failure", ["storage", "serialization"])
def test_cli_failure_has_nonzero_exit_and_no_partial_or_sensitive_output(monkeypatch, capsys, failure):
    def result(args):
        if failure == "storage":
            raise RuntimeError("private-storage-diagnostic")
        return {"private-storage-diagnostic": float("nan")}
    monkeypatch.setattr(cli, "run", result)
    with pytest.raises(SystemExit) as exc:
        cli.main(["show", "--cohort-id", "cohort"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private-storage-diagnostic" not in captured.err
    assert "No se pudo verificar" in captured.err
