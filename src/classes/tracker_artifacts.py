"""Verified artifact resolution for model-backed classic trackers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "configs" / "tracker_artifacts.json"
DEFAULT_MODELS_ROOT = PROJECT_ROOT / "models"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TrackerArtifactError(RuntimeError):
    """Raised when a tracker artifact is unavailable or cannot be trusted."""


@dataclass(frozen=True)
class ResolvedTrackerArtifact:
    artifact_id: str
    path: Path
    sha256: str
    size_bytes: int
    publisher: str
    source_url: str
    license: str


def _normalized_sha256(value: Any, *, field: str) -> str:
    digest = str(value or "").strip().lower()
    if not SHA256_PATTERN.fullmatch(digest):
        raise TrackerArtifactError(f"{field} must be a 64-character SHA-256 digest")
    return digest


def load_tracker_artifact_manifest(
    manifest_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Load and strictly validate the checked-in tracker artifact registry."""
    path = Path(manifest_path or DEFAULT_MANIFEST_PATH)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrackerArtifactError(f"Tracker artifact manifest is unreadable: {path}") from exc

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise TrackerArtifactError("Tracker artifact manifest schema is unsupported")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise TrackerArtifactError("Tracker artifact manifest has no artifacts")

    required = {
        "name",
        "version",
        "install_by_default",
        "destination",
        "url",
        "sha256",
        "size_bytes",
        "publisher",
        "source_commit",
        "source_url",
        "license",
        "license_url",
    }
    for artifact_id, record in artifacts.items():
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise TrackerArtifactError("Tracker artifact ID must be a non-empty string")
        if not isinstance(record, dict) or required - set(record):
            missing = ", ".join(sorted(required - set(record or {})))
            raise TrackerArtifactError(
                f"Tracker artifact {artifact_id!r} is missing fields: {missing}"
            )
        _normalized_sha256(record["sha256"], field=f"{artifact_id}.sha256")
        size = record["size_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise TrackerArtifactError(
                f"Tracker artifact {artifact_id!r} has an invalid size"
            )
        if not isinstance(record["install_by_default"], bool):
            raise TrackerArtifactError(
                f"Tracker artifact {artifact_id!r} has an invalid install policy"
            )
        destination = Path(str(record["destination"]))
        if destination.is_absolute() or ".." in destination.parts:
            raise TrackerArtifactError(
                f"Tracker artifact {artifact_id!r} has an unsafe destination"
            )
        if destination.parts[:1] != ("models",):
            raise TrackerArtifactError(
                f"Tracker artifact {artifact_id!r} must live under models/"
            )
    return payload


def sha256_file(path: Path, *, maximum_bytes: int) -> tuple[str, int]:
    """Hash one bounded regular file without following an artifact symlink."""
    if path.is_symlink() or not path.is_file():
        raise TrackerArtifactError(f"Tracker artifact is not a regular file: {path}")
    size = path.stat().st_size
    if size <= 0 or size > maximum_bytes:
        raise TrackerArtifactError(
            f"Tracker artifact size {size} is outside the allowed range"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest(), size


def _resolve_owned_model_path(
    value: str,
    *,
    project_root: Path,
    models_root: Path,
) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    lexical = Path(os.path.abspath(candidate))
    if models_root.is_symlink():
        raise TrackerArtifactError("Tracker model store must not be a symbolic link")
    try:
        resolved_root = models_root.resolve(strict=True)
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise TrackerArtifactError(
            f"Tracker artifact must be a regular file inside {models_root}"
        ) from exc
    if lexical != resolved:
        raise TrackerArtifactError("Tracker artifact path must not use symbolic links")
    return resolved


def resolve_tracker_artifact(
    config: Mapping[str, Any],
    *,
    project_root: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
) -> ResolvedTrackerArtifact:
    """Resolve and verify a manifest artifact or explicit operator override.

    Custom artifacts require both a model path and SHA-256. This keeps the
    runtime flexible without creating an unverified executable-model path.
    """
    root = Path(project_root or PROJECT_ROOT).resolve()
    models_root = root / "models"
    artifact_id = str(
        config.get("artifact_id", "opencv_vittrack_2023sep")
    ).strip()
    path_override = str(config.get("model_path_override", "") or "").strip()
    digest_override = str(config.get("model_sha256_override", "") or "").strip()
    if bool(path_override) != bool(digest_override):
        raise TrackerArtifactError(
            "VitTrack custom model path and SHA-256 must be configured together"
        )

    manifest = load_tracker_artifact_manifest(
        manifest_path or root / "configs" / "tracker_artifacts.json"
    )
    artifacts = manifest["artifacts"]
    record = artifacts.get(artifact_id)
    if not isinstance(record, dict):
        available = ", ".join(sorted(artifacts))
        raise TrackerArtifactError(
            f"Unknown tracker artifact {artifact_id!r}; available: {available}"
        )

    if path_override:
        configured_path = path_override
        expected_sha = _normalized_sha256(
            digest_override,
            field="model_sha256_override",
        )
        expected_size = int(config.get("model_max_bytes", 16 * 1024 * 1024))
        publisher = "operator-configured"
        source_url = ""
        license_name = "operator-reviewed"
        resolved_id = "custom"
    else:
        configured_path = str(record["destination"])
        expected_sha = _normalized_sha256(record["sha256"], field="sha256")
        expected_size = int(record["size_bytes"])
        publisher = str(record["publisher"])
        source_url = str(record["source_url"])
        license_name = str(record["license"])
        resolved_id = artifact_id

    if expected_size <= 0 or expected_size > 64 * 1024 * 1024:
        raise TrackerArtifactError("VitTrack model_max_bytes is outside the supported range")
    path = _resolve_owned_model_path(
        configured_path,
        project_root=root,
        models_root=models_root,
    )
    if hasattr(os, "geteuid") and path.stat().st_uid != os.geteuid():
        raise TrackerArtifactError(
            "Tracker artifact must be owned by the PixEagle runtime user"
        )
    observed_sha, observed_size = sha256_file(path, maximum_bytes=expected_size)
    if observed_sha != expected_sha:
        raise TrackerArtifactError(
            f"Tracker artifact checksum mismatch: {path.name}"
        )
    if not path_override and observed_size != int(record["size_bytes"]):
        raise TrackerArtifactError(
            f"Tracker artifact size mismatch: {path.name}"
        )
    return ResolvedTrackerArtifact(
        artifact_id=resolved_id,
        path=path,
        sha256=observed_sha,
        size_bytes=observed_size,
        publisher=publisher,
        source_url=source_url,
        license=license_name,
    )
