"""OpenCV VitTrack adapter with PixEagle's shared fail-closed lifecycle."""

from __future__ import annotations

import logging
from typing import Optional

import cv2
from classes.tracker_artifacts import (
    ResolvedTrackerArtifact,
    TrackerArtifactError,
    resolve_tracker_artifact,
)
from classes.trackers.model_backed_tracker import OpenCVNativeScoreTracker


logger = logging.getLogger(__name__)


class VitTrackTracker(OpenCVNativeScoreTracker):
    """Model-backed short-term tracker using OpenCV's VitTrack API.

    VitTrack supplies appearance-aware proposals and a native tracking score.
    PixEagle still owns motion/scale/appearance validation, measurement
    freshness, estimator hints, and detector-assisted recovery.
    """

    TRACKER_ALGORITHM = "VitTrack"
    CONFIG_SECTION = "VitTrack_Tracker"

    def __init__(
        self,
        video_handler: Optional[object] = None,
        detector: Optional[object] = None,
        app_controller: Optional[object] = None,
    ):
        self._artifact: Optional[ResolvedTrackerArtifact] = None
        super().__init__(video_handler, detector, app_controller)

    def _create_tracker(self):
        config = self._tracker_config()
        if not hasattr(cv2, "TrackerVit_Params") or not hasattr(
            cv2, "TrackerVit_create"
        ):
            raise RuntimeError(
                "VitTrack is unavailable in the active OpenCV provider; "
                "run make repair or select another classic tracker"
            )
        try:
            artifact = resolve_tracker_artifact(config)
        except TrackerArtifactError as exc:
            raise RuntimeError(
                "VitTrack model is missing or unverified; run "
                "make install-tracker-artifacts, then retry"
            ) from exc

        params = cv2.TrackerVit_Params()
        params.net = str(artifact.path)
        try:
            params.backend = int(config.get("backend_id", 0))
            params.target = int(config.get("target_id", 0))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "VitTrack backend_id and target_id must be integer OpenCV DNN IDs"
            ) from exc
        params.tracking_score_threshold = self._bounded_fraction(
            config.get("native_score_threshold", 0.20),
            fallback=0.20,
        )
        tracker = cv2.TrackerVit_create(params)
        if tracker is None:
            raise RuntimeError("OpenCV could not create the VitTrack runtime")
        self._artifact = artifact
        logger.info(
            "VitTrack artifact verified: %s (%s)",
            artifact.path.name,
            artifact.sha256[:12],
        )
        return tracker

    def _artifact_raw_data(self) -> dict:
        return {
            "artifact_id": self._artifact.artifact_id if self._artifact else None,
        }

    def _artifact_metadata(self) -> dict:
        metadata = {}
        if self._artifact:
            metadata.update(
                {
                    "artifact_id": self._artifact.artifact_id,
                    "artifact_sha256": self._artifact.sha256,
                    "artifact_publisher": self._artifact.publisher,
                    "artifact_license": self._artifact.license,
                }
            )
        return metadata
