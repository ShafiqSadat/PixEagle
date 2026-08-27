#!/usr/bin/env python3
"""Install checksum-pinned model artifacts for classic trackers."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import urllib.error
import urllib.request


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_PROJECT_ROOT = SCRIPT_PATH.parents[2]
sys.path.insert(0, str(DEFAULT_PROJECT_ROOT / "src"))

from classes.tracker_artifacts import (  # noqa: E402
    TrackerArtifactError,
    load_tracker_artifact_manifest,
    resolve_tracker_artifact,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or verify pinned classic-tracker model artifacts."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="PixEagle checkout root",
    )
    parser.add_argument(
        "--artifact",
        action="append",
        dest="artifacts",
        help="Artifact ID to process; repeat for multiple IDs (default: all)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify local artifacts without downloading missing files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the pinned plan without writing files",
    )
    return parser.parse_args()


def _safe_destination(root: Path, relative: str) -> Path:
    models_root = root / "models"
    destination = Path(relative)
    if destination.is_absolute() or ".." in destination.parts:
        raise TrackerArtifactError("Artifact destination is unsafe")
    lexical = Path(os.path.abspath(root / destination))
    expected_parent = Path(os.path.abspath(models_root))
    try:
        lexical.relative_to(expected_parent)
    except ValueError as exc:
        raise TrackerArtifactError("Artifact destination escaped models/") from exc
    if models_root.is_symlink() or lexical.is_symlink():
        raise TrackerArtifactError("Artifact destination must not use symbolic links")
    return lexical


def _prepare_destination(destination: Path, models_root: Path) -> None:
    models_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if models_root.is_symlink() or not models_root.is_dir():
        raise TrackerArtifactError("Model store must be a regular directory")
    os.chmod(models_root, stat.S_IRWXU)
    current = models_root
    for component in destination.parent.relative_to(models_root).parts:
        current = current / component
        if current.is_symlink():
            raise TrackerArtifactError("Artifact destination parent is a symbolic link")
        current.mkdir(mode=0o700, exist_ok=True)
        os.chmod(current, stat.S_IRWXU)


def _download(record: dict[str, object], destination: Path) -> None:
    expected_size = int(record["size_bytes"])
    expected_sha = str(record["sha256"])
    request = urllib.request.Request(
        str(record["url"]),
        headers={"User-Agent": "PixEagle-tracker-artifact-installer/1"},
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".part",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    observed_size = 0
    try:
        with os.fdopen(descriptor, "wb") as output:
            with urllib.request.urlopen(request, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    observed_size += len(chunk)
                    if observed_size > expected_size:
                        raise TrackerArtifactError(
                            "Downloaded tracker artifact exceeded its manifest size"
                        )
                    digest.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if observed_size != expected_size or digest.hexdigest() != expected_sha:
            raise TrackerArtifactError(
                "Downloaded tracker artifact failed size or checksum verification"
            )
        os.chmod(temporary_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def _record_provenance(root: Path, artifact_id: str, record: dict[str, object]) -> None:
    log_path = root / "models" / ".tracker-artifact-provenance.jsonl"
    payload = {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "artifact_id": artifact_id,
        "name": record["name"],
        "version": record["version"],
        "install_by_default": record["install_by_default"],
        "source_commit": record["source_commit"],
        "source_url": record["source_url"],
        "url": record["url"],
        "sha256": record["sha256"],
        "size_bytes": record["size_bytes"],
        "destination": record["destination"],
        "license": record["license"],
        "license_url": record["license_url"],
        "verification": "sha256",
    }
    descriptor = os.open(
        log_path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(log_path, stat.S_IRUSR | stat.S_IWUSR)


def main() -> int:
    args = _parse_args()
    root = args.project_root.expanduser().resolve()
    manifest_path = root / "configs" / "tracker_artifacts.json"
    try:
        manifest = load_tracker_artifact_manifest(manifest_path)
        available = manifest["artifacts"]
        selected = args.artifacts or [
            artifact_id
            for artifact_id, record in available.items()
            if record.get("install_by_default") is True
        ]
        if not selected:
            raise TrackerArtifactError("No default tracker artifacts are configured")
        unknown = sorted(set(selected) - set(available))
        if unknown:
            raise TrackerArtifactError(
                f"Unknown tracker artifact(s): {', '.join(unknown)}"
            )

        for artifact_id in selected:
            record = available[artifact_id]
            destination = _safe_destination(root, str(record["destination"]))
            print(f"[*] {record['name']}: {destination.relative_to(root)}")
            print(f"    SHA-256: {record['sha256']}")
            if args.dry_run:
                print(f"    URL: {record['url']}")
                continue

            try:
                resolved = resolve_tracker_artifact(
                    {"artifact_id": artifact_id},
                    project_root=root,
                    manifest_path=manifest_path,
                )
                print(f"[OK] Existing artifact verified ({resolved.size_bytes} bytes)")
                continue
            except TrackerArtifactError as exc:
                if destination.exists():
                    raise TrackerArtifactError(
                        f"Existing artifact is untrusted and was preserved: {destination} ({exc})"
                    ) from exc
                if args.verify_only:
                    raise

            _prepare_destination(destination, root / "models")
            print("[*] Downloading verified tracker artifact...")
            _download(record, destination)
            resolved = resolve_tracker_artifact(
                {"artifact_id": artifact_id},
                project_root=root,
                manifest_path=manifest_path,
            )
            _record_provenance(root, artifact_id, record)
            print(f"[OK] Installed and verified ({resolved.size_bytes} bytes)")
        return 0
    except (TrackerArtifactError, OSError, urllib.error.URLError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
