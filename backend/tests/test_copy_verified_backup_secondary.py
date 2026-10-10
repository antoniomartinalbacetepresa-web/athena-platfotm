from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.database_backup_service import DatabaseBackupService
from scripts.copy_verified_backup_secondary import copy_verified_backup


def _backup(tmp_path: Path) -> tuple[Path, Path]:
    database = AthenaDatabase(tmp_path / "live" / "athena.db")
    database.initialize()
    service = DatabaseBackupService(database)
    backup = tmp_path / "primary" / "athena-test.db"
    service.create_backup(backup)
    return backup, service.manifest_path_for(backup)


def test_verified_secondary_copy_preserves_manifest_digest(tmp_path: Path) -> None:
    backup, manifest = _backup(tmp_path)
    result = copy_verified_backup(backup_path=backup, manifest_path=manifest, destination_directory=tmp_path / "secondary")
    assert result["status"] == "secondary_copy_verified"
    assert Path(result["backup"]).read_bytes() == backup.read_bytes()
    assert Path(result["manifest"]).read_text() == manifest.read_text()
    assert result["sha256"] == json.loads(manifest.read_text())["sha256"]
    assert result["policy"] == {
        "secondaryCopyVerified": True,
        "offsiteLocationOperatorAttested": False,
        "offsiteLocationVerified": False,
        "scheduledExecutionVerified": False,
        "productionRecoveryVerified": False,
    }


def test_secondary_copy_rejects_same_primary_directory(tmp_path: Path) -> None:
    backup, manifest = _backup(tmp_path)
    with pytest.raises(ValueError, match="destino secundario"):
        copy_verified_backup(backup_path=backup, manifest_path=manifest, destination_directory=backup.parent)


def test_secondary_copy_rejects_tampered_primary_before_copy(tmp_path: Path) -> None:
    backup, manifest = _backup(tmp_path)
    backup.write_bytes(backup.read_bytes() + b"tampered")
    with pytest.raises(RuntimeError, match="manifiesto"):
        copy_verified_backup(backup_path=backup, manifest_path=manifest, destination_directory=tmp_path / "secondary")
    assert not (tmp_path / "secondary").exists()


def test_secondary_copy_never_overwrites_existing_evidence(tmp_path: Path) -> None:
    backup, manifest = _backup(tmp_path)
    destination = tmp_path / "secondary"
    copy_verified_backup(backup_path=backup, manifest_path=manifest, destination_directory=destination)
    with pytest.raises(FileExistsError, match="ya contiene"):
        copy_verified_backup(backup_path=backup, manifest_path=manifest, destination_directory=destination)


def test_operator_attestation_is_recorded_but_never_promoted_to_verified_offsite_evidence(tmp_path: Path) -> None:
    backup, manifest = _backup(tmp_path)
    result = copy_verified_backup(
        backup_path=backup,
        manifest_path=manifest,
        destination_directory=tmp_path / "operator-declared-offsite",
        offsite_attested=True,
    )
    assert result["policy"]["secondaryCopyVerified"] is True
    assert result["policy"]["offsiteLocationOperatorAttested"] is True
    assert result["policy"]["offsiteLocationVerified"] is False
    assert result["policy"]["scheduledExecutionVerified"] is False
    assert result["policy"]["productionRecoveryVerified"] is False


def test_secondary_copy_does_not_infer_offsite_from_different_path(tmp_path: Path) -> None:
    backup, manifest = _backup(tmp_path)
    result = copy_verified_backup(
        backup_path=backup,
        manifest_path=manifest,
        destination_directory=tmp_path / "looks-remote-but-is-not-evidence",
    )
    assert result["policy"]["offsiteLocationOperatorAttested"] is False
    assert result["policy"]["offsiteLocationVerified"] is False
