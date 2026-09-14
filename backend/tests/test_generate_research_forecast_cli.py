"""Synthetic CLI tests; no production forecasts or model-quality evidence."""
import hashlib
import json

import pytest

from scripts import generate_research_forecast as cli


def arguments(tmp_path, template=b'{}', model=b'{"test":"data"}'):
    model_path, template_path = tmp_path / "model.json", tmp_path / "template.json"
    model_path.write_bytes(model)
    template_path.write_bytes(template)
    return cli.build_parser().parse_args([
        "--model", str(model_path), "--template", str(template_path),
        "--artifact-sha256", hashlib.sha256(model).hexdigest()])


class Store:
    def generate_and_persist(self, **kwargs):
        return kwargs


def test_forwards_exact_bytes_template_and_pin(tmp_path):
    args = arguments(tmp_path, template=b'{"specificationId":"test-only"}')
    result = cli.run(args, store=Store())
    assert result["model_bytes"] == args.model.read_bytes()
    assert result["pinned_artifact_hash"] == args.artifact_sha256
    assert result["specification_template"] == {"specificationId": "test-only"}


@pytest.mark.parametrize("pin", ["invalid", "a" * 64])
def test_wrong_pin_fails_before_generation(tmp_path, pin):
    args = arguments(tmp_path)
    args.artifact_sha256 = pin
    with pytest.raises(ValueError):
        cli.run(args, store=Store())


def test_duplicate_template_keys_rejected(tmp_path):
    args = arguments(tmp_path, template=b'{"x":1,"x":2}')
    with pytest.raises(ValueError):
        cli.run(args, store=Store())


@pytest.mark.parametrize("content", [b"", b"abcd"])
def test_bounded_read_rejects_empty_and_oversized_file(tmp_path, content):
    path = tmp_path / "data"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        cli._read_limited(path, 3)


def test_main_failure_has_no_partial_json_or_internal_details(monkeypatch, capsys):
    def unavailable(args):
        raise RuntimeError("private-internal-detail")
    monkeypatch.setattr(cli, "run", unavailable)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--model", "model", "--template", "template", "--artifact-sha256", "a" * 64])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private-internal-detail" not in captured.err
