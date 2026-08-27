"""Policy and integration tests for classic-tracker model artifacts."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from classes.tracker_artifacts import (
    TrackerArtifactError,
    load_tracker_artifact_manifest,
    resolve_tracker_artifact,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_ROOT / "scripts" / "setup" / "install-tracker-artifacts.py"
MANIFEST = PROJECT_ROOT / "configs" / "tracker_artifacts.json"


def _manifest_record(payload: bytes, *, url: str) -> dict:
    return {
        "schema_version": 1,
        "artifacts": {
            "test_artifact": {
                "name": "Test artifact",
                "version": "1",
                "install_by_default": True,
                "destination": "models/classic/test.onnx",
                "url": url,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "publisher": "test",
                "source_commit": "a" * 40,
                "source_url": "https://example.invalid/source",
                "license": "Apache-2.0",
                "license_url": "https://example.invalid/license",
            }
        },
    }


def _write_project(tmp_path: Path, payload: bytes) -> Path:
    source = tmp_path / "source.onnx"
    source.write_bytes(payload)
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "tracker_artifacts.json").write_text(
        json.dumps(_manifest_record(payload, url=source.as_uri())),
        encoding="utf-8",
    )
    return source


def test_checked_in_tracker_artifact_manifest_is_pinned_and_licensed():
    payload = load_tracker_artifact_manifest(MANIFEST)
    record = payload["artifacts"]["opencv_vittrack_2023sep"]

    assert record["source_commit"] in record["url"]
    assert record["sha256"] == "2990f0b7cd44d92afa48cd97db6de7be113fc1d9594fddb74e2725c10478e91d"
    assert record["size_bytes"] == 714726
    assert record["license"] == "Apache-2.0"
    assert "/main/" not in record["url"]

    dasiamrpn = {
        artifact_id: artifact
        for artifact_id, artifact in payload["artifacts"].items()
        if artifact.get("tracker") == "DaSiamRPN"
    }
    assert set(dasiamrpn) == {
        "opencv_dasiamrpn_model",
        "opencv_dasiamrpn_kernel_r1",
        "opencv_dasiamrpn_kernel_cls1",
    }
    assert sum(item["size_bytes"] for item in dasiamrpn.values()) == 161851280
    assert all(item["install_by_default"] is False for item in dasiamrpn.values())
    assert all(item["license"] == "MIT" for item in dasiamrpn.values())


def test_artifact_installer_downloads_atomically_and_reuses_verified_file(tmp_path):
    payload = b"verified-tracker-model"
    _write_project(tmp_path, payload)
    command = [
        sys.executable,
        str(INSTALLER),
        "--project-root",
        str(tmp_path),
    ]

    first = subprocess.run(command, check=False, text=True, capture_output=True)
    second = subprocess.run(command, check=False, text=True, capture_output=True)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "Installed and verified" in first.stdout
    assert "Existing artifact verified" in second.stdout
    destination = tmp_path / "models" / "classic" / "test.onnx"
    assert destination.read_bytes() == payload
    provenance = tmp_path / "models" / ".tracker-artifact-provenance.jsonl"
    assert json.loads(provenance.read_text(encoding="utf-8"))["artifact_id"] == "test_artifact"


def test_artifact_installer_preserves_mismatched_existing_file(tmp_path):
    _write_project(tmp_path, b"expected")
    destination = tmp_path / "models" / "classic" / "test.onnx"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"operator-data")

    result = subprocess.run(
        [sys.executable, str(INSTALLER), "--project-root", str(tmp_path)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "untrusted and was preserved" in result.stderr
    assert destination.read_bytes() == b"operator-data"


def test_custom_artifact_requires_matching_path_and_digest(tmp_path):
    payload = b"custom-model"
    _write_project(tmp_path, b"manifest-model")
    model = tmp_path / "models" / "custom" / "model.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    resolved = resolve_tracker_artifact(
        {
            "artifact_id": "test_artifact",
            "model_path_override": "models/custom/model.onnx",
            "model_sha256_override": digest,
            "model_max_bytes": 1024,
        },
        project_root=tmp_path,
    )
    assert resolved.artifact_id == "custom"
    assert resolved.path == model

    with pytest.raises(TrackerArtifactError, match="configured together"):
        resolve_tracker_artifact(
            {
                "artifact_id": "test_artifact",
                "model_path_override": "models/custom/model.onnx",
            },
            project_root=tmp_path,
        )


def test_named_artifact_fields_support_multi_file_trackers(tmp_path):
    payload = b"custom-kernel"
    _write_project(tmp_path, b"manifest-model")
    model = tmp_path / "models" / "custom" / "kernel.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(payload)

    resolved = resolve_tracker_artifact(
        {
            "kernel_artifact_id": "test_artifact",
            "kernel_path": "models/custom/kernel.onnx",
            "kernel_sha256": hashlib.sha256(payload).hexdigest(),
            "kernel_max_bytes": 1024,
        },
        project_root=tmp_path,
        artifact_id_field="kernel_artifact_id",
        path_override_field="kernel_path",
        digest_override_field="kernel_sha256",
        max_bytes_field="kernel_max_bytes",
        default_artifact_id="test_artifact",
    )

    assert resolved.artifact_id == "custom"
    assert resolved.path == model


def test_setup_surfaces_one_nonfatal_vittrack_repair_command():
    init_text = (PROJECT_ROOT / "scripts" / "init.sh").read_text(encoding="utf-8")
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "setup_classic_tracker_artifacts" in init_text
    assert "VitTrack unavailable; other trackers remain usable" in init_text
    assert "make install-tracker-artifacts" in init_text
    assert "install-tracker-artifacts:" in makefile
    assert "install-dasiamrpn-artifacts:" in makefile
    assert "Install DaSiamRPN tracker models (~155 MiB)? [y/N]:" in init_text
