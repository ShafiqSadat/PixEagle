"""OpenCV VitTrack adapter with PixEagle's shared fail-closed lifecycle."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import cv2
import numpy as np

from classes.tracker_artifacts import (
    ResolvedTrackerArtifact,
    TrackerArtifactError,
    resolve_tracker_artifact,
)
from classes.trackers.csrt_tracker import CSRTTracker


logger = logging.getLogger(__name__)


class VitTrackTracker(CSRTTracker):
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
        self.native_tracking_score = 0.0
        self._artifact: Optional[ResolvedTrackerArtifact] = None
        super().__init__(video_handler, detector, app_controller)
        config = self._tracker_config()
        self.model_score_weight = self._bounded_fraction(
            config.get("model_score_weight", 0.65),
            fallback=0.65,
        )

    @staticmethod
    def _bounded_fraction(value, *, fallback: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return fallback
        if not np.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            return fallback
        return numeric

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

    def _read_native_score(self) -> float:
        try:
            score = self.tracker.getTrackingScore()
        except (AttributeError, TypeError, ValueError, cv2.error):
            self.native_tracking_score = 0.0
            return 0.0
        self.native_tracking_score = self._normalize_confidence(score)
        return self.native_tracking_score

    def _evaluate_candidate_confidence(self, frame, bbox) -> float:
        validated_score = super()._evaluate_candidate_confidence(frame, bbox)
        native_score = self._read_native_score()
        return self._normalize_confidence(
            self.model_score_weight * native_score
            + (1.0 - self.model_score_weight) * validated_score
        )

    def update(
        self,
        frame: np.ndarray,
    ) -> Tuple[bool, Tuple[int, int, int, int]]:
        result = super().update(frame)
        self._read_native_score()
        return result

    def _output_quality_metrics(self) -> dict:
        quality = super()._output_quality_metrics()
        quality["native_tracking_score"] = self.native_tracking_score
        return quality

    def _output_raw_data(self) -> dict:
        raw = super()._output_raw_data()
        raw.update(
            {
                "model_score_weight": self.model_score_weight,
                "artifact_id": self._artifact.artifact_id if self._artifact else None,
            }
        )
        return raw

    def _output_metadata(self) -> dict:
        metadata = super()._output_metadata()
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

    def get_capabilities(self) -> dict:
        capabilities = super().get_capabilities()
        capabilities.update(
            {
                "tracker_algorithm": self.TRACKER_ALGORITHM,
                "supports_rotation": False,
                "supports_scale_change": True,
                "supports_occlusion": False,
                "model_backed": True,
                "native_confidence": True,
                "prediction_command_eligible": False,
            }
        )
        return capabilities
