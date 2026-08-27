"""OpenCV DaSiamRPN adapter with PixEagle's shared fail-closed lifecycle."""

from __future__ import annotations

import logging
from typing import Dict, Optional

import cv2

from classes.tracker_artifacts import (
    ResolvedTrackerArtifact,
    TrackerArtifactError,
    resolve_tracker_artifact,
)
from classes.trackers.model_backed_tracker import OpenCVNativeScoreTracker


logger = logging.getLogger(__name__)


class DaSiamRPNTracker(OpenCVNativeScoreTracker):
    """Distractor-aware Siamese tracker using OpenCV's DaSiamRPN runtime."""

    TRACKER_ALGORITHM = "DaSiamRPN"
    CONFIG_SECTION = "DaSiamRPN_Tracker"

    _ARTIFACT_FIELDS = {
        "model": (
            "model_artifact_id",
            "model_path_override",
            "model_sha256_override",
            "model_max_bytes",
            "opencv_dasiamrpn_model",
        ),
        "kernel_r1": (
            "kernel_r1_artifact_id",
            "kernel_r1_path_override",
            "kernel_r1_sha256_override",
            "kernel_r1_max_bytes",
            "opencv_dasiamrpn_kernel_r1",
        ),
        "kernel_cls1": (
            "kernel_cls1_artifact_id",
            "kernel_cls1_path_override",
            "kernel_cls1_sha256_override",
            "kernel_cls1_max_bytes",
            "opencv_dasiamrpn_kernel_cls1",
        ),
    }

    def __init__(self, video_handler=None, detector=None, app_controller=None):
        self._artifacts: Dict[str, ResolvedTrackerArtifact] = {}
        super().__init__(video_handler, detector, app_controller)
        self.use_shared_appearance_validation = bool(
            self._tracker_config().get("use_shared_appearance_validation", False)
        )

    def _resolve_artifacts(self) -> Dict[str, ResolvedTrackerArtifact]:
        config = self._tracker_config()
        resolved = {}
        for role, fields in self._ARTIFACT_FIELDS.items():
            artifact_field, path_field, digest_field, max_field, default_id = fields
            resolved[role] = resolve_tracker_artifact(
                config,
                artifact_id_field=artifact_field,
                path_override_field=path_field,
                digest_override_field=digest_field,
                max_bytes_field=max_field,
                default_artifact_id=default_id,
            )
        return resolved

    def _create_tracker(self):
        if not hasattr(cv2, "TrackerDaSiamRPN_Params") or not hasattr(
            cv2, "TrackerDaSiamRPN_create"
        ):
            raise RuntimeError(
                "DaSiamRPN is unavailable in the active OpenCV provider; "
                "run make repair or select another classic tracker"
            )
        try:
            artifacts = self._resolve_artifacts()
        except TrackerArtifactError as exc:
            raise RuntimeError(
                "DaSiamRPN models are missing or unverified; run "
                "make install-dasiamrpn-artifacts, then retry"
            ) from exc

        config = self._tracker_config()
        params = cv2.TrackerDaSiamRPN_Params()
        params.model = str(artifacts["model"].path)
        params.kernel_r1 = str(artifacts["kernel_r1"].path)
        params.kernel_cls1 = str(artifacts["kernel_cls1"].path)
        try:
            params.backend = int(config.get("backend_id", 0))
            params.target = int(config.get("target_id", 0))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "DaSiamRPN backend_id and target_id must be integer OpenCV DNN IDs"
            ) from exc
        tracker = cv2.TrackerDaSiamRPN_create(params)
        if tracker is None:
            raise RuntimeError("OpenCV could not create the DaSiamRPN runtime")
        self._artifacts = artifacts
        logger.info(
            "DaSiamRPN artifacts verified: %s",
            ", ".join(
                f"{role}={artifact.sha256[:12]}"
                for role, artifact in sorted(artifacts.items())
            ),
        )
        return tracker

    def _appearance_is_valid(self) -> bool:
        if not self.use_shared_appearance_validation:
            return True
        return super()._appearance_is_valid()

    def _artifact_raw_data(self) -> dict:
        return {
            "artifact_ids": {
                role: artifact.artifact_id
                for role, artifact in sorted(self._artifacts.items())
            },
            "shared_appearance_validation": self.use_shared_appearance_validation,
        }

    def _artifact_metadata(self) -> dict:
        return {
            "artifacts": {
                role: {
                    "artifact_id": artifact.artifact_id,
                    "sha256": artifact.sha256,
                    "publisher": artifact.publisher,
                    "license": artifact.license,
                }
                for role, artifact in sorted(self._artifacts.items())
            }
        }
