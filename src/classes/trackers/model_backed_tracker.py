"""Shared OpenCV native-score adapter for model-backed classic trackers."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import cv2
import numpy as np

from classes.config_service import ConfigService
from classes.trackers import csrt_tracker
from classes.trackers.csrt_tracker import CSRTTracker


class OpenCVNativeScoreTracker(CSRTTracker):
    """Blend an OpenCV tracker's native score with shared PixEagle validation."""

    def _tracker_config(self) -> dict:
        """Layer sparse runtime overrides over this release's section defaults."""
        configured = getattr(csrt_tracker.Parameters, self.CONFIG_SECTION, None)
        return ConfigService.get_instance().get_effective_section(
            self.CONFIG_SECTION,
            overrides=configured if isinstance(configured, dict) else None,
        )

    def __init__(self, video_handler=None, detector=None, app_controller=None):
        self.native_tracking_score = 0.0
        super().__init__(video_handler, detector, app_controller)
        config = self._tracker_config()
        self.native_score_threshold = self._bounded_fraction(
            config.get("native_score_threshold", 0.20),
            fallback=0.20,
        )
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
        if native_score < self.native_score_threshold:
            return 0.0
        return self._normalize_confidence(
            self.model_score_weight * native_score
            + (1.0 - self.model_score_weight) * validated_score
        )

    def _confidence_is_valid(self, confidence: float) -> bool:
        """Keep native model confidence as a hard gate, independent of blending."""
        return (
            self.native_tracking_score >= self.native_score_threshold
            and super()._confidence_is_valid(confidence)
        )

    def update(self, frame: np.ndarray) -> Tuple[bool, Tuple[int, int, int, int]]:
        result = super().update(frame)
        self._read_native_score()
        return result

    def _artifact_raw_data(self) -> Dict[str, Any]:
        return {}

    def _artifact_metadata(self) -> Dict[str, Any]:
        return {}

    def _output_quality_metrics(self) -> dict:
        quality = super()._output_quality_metrics()
        quality["native_tracking_score"] = self.native_tracking_score
        return quality

    def _output_raw_data(self) -> dict:
        raw = super()._output_raw_data()
        raw.update(
            {
                "native_score_threshold": self.native_score_threshold,
                "model_score_weight": self.model_score_weight,
            }
        )
        raw.update(self._artifact_raw_data())
        return raw

    def _output_metadata(self) -> dict:
        metadata = super()._output_metadata()
        metadata.update(self._artifact_metadata())
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
