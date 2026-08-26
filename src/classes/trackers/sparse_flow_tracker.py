"""Classic sparse optical-flow tracker with fail-closed measurements."""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from classes.parameters import Parameters
from classes.tracker_output import TrackerOutput
from classes.trackers.base_tracker import BaseTracker
from classes.trackers.sparse_flow_core import (
    BBox,
    SparseFlowConfig,
    SparseFlowCore,
    SparseFlowMetrics,
    SparseFlowProposal,
)


logger = logging.getLogger(__name__)


class SparseFlowTracker(BaseTracker):
    """High-rate short-term tracker using validated sparse point motion.

    Optical flow, geometry, and appearance produce candidate measurements. The
    application controller remains responsible for estimator prediction,
    detector-assisted re-detection, and command freshness.
    """

    def __init__(
        self,
        video_handler: Optional[object] = None,
        detector: Optional[object] = None,
        app_controller: Optional[object] = None,
    ) -> None:
        super().__init__(video_handler, detector, app_controller)
        self.tracker_name = "SparseFlow"
        self.config = SparseFlowConfig.from_mapping(
            getattr(Parameters, "SparseFlow_Tracker", {})
        )
        self.flow_core = SparseFlowCore(self.config)
        self.failure_threshold = self.config.failure_threshold
        self.max_scale_change = self.config.max_scale_change_per_frame
        self.last_flow_metrics = SparseFlowMetrics()
        self.last_flow_reason = "inactive"
        if self.position_estimator:
            self.position_estimator.reset()

    def _create_tracker(self):
        """Sparse Flow uses a proposal/commit core rather than an OpenCV tracker object."""
        return None

    def start_tracking(self, frame: np.ndarray, bbox: BBox) -> None:
        logger.info("Initializing Sparse Flow tracker with bbox: %s", bbox)
        accepted_bbox = self.flow_core.initialize(frame, bbox)
        self._initialize_detector_target(frame, accepted_bbox)

        self.bbox = accepted_bbox
        self.prev_bbox = accepted_bbox
        self.predicted_bbox = None
        self.prev_center = None
        self.set_center(self._bbox_center(accepted_bbox))
        self.normalize_bbox()
        self.center_history.clear()
        self.center_history.append(self.center)
        self.tracking_started = True
        self.last_measurement_timestamp = time.time()
        self.last_failure_info = None
        self.last_flow_metrics = SparseFlowMetrics(
            source_point_count=self.flow_core.point_count,
            forward_valid_count=self.flow_core.point_count,
            retained_point_count=self.flow_core.point_count,
            inlier_ratio=1.0,
            appearance_confidence=1.0,
            confidence=1.0,
            transform_model="initial_roi",
        )
        self.last_flow_reason = "measurement"
        self.confidence = 1.0
        self.motion_confidence = 1.0
        self.appearance_confidence = 1.0
        self.failure_count = 0
        self.frame_count = 0
        self.successful_frames = 0
        self.failed_frames = 0
        self.raw_confidence_history.clear()
        self.last_update_time = time.monotonic()
        self._initialize_estimator(self.center)

    def update(self, frame: np.ndarray) -> Tuple[bool, BBox]:
        if not self.tracking_started or self.bbox is None:
            return False, self.bbox

        started_at = time.time()
        dt = self.update_time()
        if self.override_active:
            return self._handle_smart_tracker_override(frame, dt)

        proposal = self.flow_core.propose(frame)
        self.last_flow_metrics = proposal.metrics
        self.last_flow_reason = proposal.reason
        if not proposal.success or proposal.bbox is None:
            return self._handle_failure(frame, started_at, proposal.reason)

        candidate_bbox = proposal.bbox
        estimator_prediction = self._get_estimator_prediction(dt)
        motion_valid = self._validate_bbox_motion(candidate_bbox, estimator_prediction)
        scale_valid = self._validate_bbox_scale(
            candidate_bbox,
            reference_bbox=self.prev_bbox,
        )
        candidate_center = self._bbox_center(candidate_bbox)
        self.motion_confidence = self._normalize_confidence(
            self._compute_motion_confidence_between(candidate_center, self.center)
        )
        self.appearance_confidence = proposal.metrics.appearance_confidence
        boundary_penalty = self.compute_boundary_confidence_penalty_for_bbox(
            candidate_bbox
        )
        raw_confidence = self._normalize_confidence(
            proposal.metrics.confidence * boundary_penalty
        )
        self.confidence = raw_confidence

        if not motion_valid:
            return self._handle_failure(frame, started_at, "motion_invalid")
        if not scale_valid:
            return self._handle_failure(frame, started_at, "scale_invalid")
        if raw_confidence < self.config.confidence_threshold:
            return self._handle_failure(frame, started_at, "low_confidence")

        return self._accept_measurement(
            frame,
            proposal,
            raw_confidence,
            dt,
            started_at,
        )

    def _accept_measurement(
        self,
        frame: np.ndarray,
        proposal: SparseFlowProposal,
        confidence: float,
        dt: float,
        started_at: float,
    ) -> Tuple[bool, BBox]:
        self.flow_core.commit(proposal, confidence)
        bbox = proposal.bbox
        if bbox is None:
            raise RuntimeError("Successful Sparse Flow proposal has no bbox")

        self.prev_center = self.center
        self.bbox = bbox
        self.set_center(self._bbox_center(bbox))
        self.normalize_bbox()
        self.center_history.append(self.center)
        self.confidence = confidence
        self._update_appearance_model_safe(frame, bbox)
        self._update_estimator(dt)
        self._update_out_of_frame_status(frame)
        self.prev_bbox = bbox
        self.predicted_bbox = None
        self.last_measurement_timestamp = time.time()
        self.last_failure_info = None
        self.last_flow_reason = "measurement"
        self.failure_count = 0
        self.successful_frames += 1
        self.frame_count += 1
        self._log_performance(started_at)
        return True, bbox

    def _handle_failure(
        self,
        frame: np.ndarray,
        started_at: float,
        reason: str,
    ) -> Tuple[bool, BBox]:
        self._record_loss_start()
        self.failure_count += 1
        self.failed_frames += 1
        self.frame_count += 1
        self.last_flow_reason = reason
        self._update_out_of_frame_status(frame)
        self._build_failure_info(reason)
        self._log_performance(started_at)
        if self.failure_count == self.failure_threshold:
            logger.warning(
                "Sparse Flow lost a usable measurement after %d consecutive failures (%s)",
                self.failure_count,
                reason,
            )
        return False, self.bbox

    @staticmethod
    def _bbox_center(bbox: BBox) -> Tuple[int, int]:
        return (
            int(round(bbox[0] + bbox[2] / 2.0)),
            int(round(bbox[1] + bbox[3] / 2.0)),
        )

    def stop_tracking(self) -> None:
        super().stop_tracking()
        self.flow_core.reset()
        self.last_flow_metrics = SparseFlowMetrics()
        self.last_flow_reason = "inactive"

    def reset(self) -> None:
        super().reset()
        if hasattr(self, "flow_core"):
            self.flow_core.reset()
        self.last_flow_metrics = SparseFlowMetrics()
        self.last_flow_reason = "inactive"

    def get_output(self) -> TrackerOutput:
        metrics = self.last_flow_metrics
        return self._build_output(
            tracker_algorithm="SparseFlow",
            extra_quality={
                "point_retention": (
                    metrics.retained_point_count
                    / max(1, metrics.source_point_count)
                ),
                "flow_consistency": (
                    max(
                        0.0,
                        1.0
                        - metrics.median_fb_error_px
                        / max(metrics.fb_threshold_px, 1e-6),
                    )
                    if metrics.fb_threshold_px > 0.0
                    else 0.0
                ),
                "geometry_inlier_ratio": metrics.inlier_ratio,
                "appearance_confidence": metrics.appearance_confidence,
            },
            extra_raw={
                "flow_reason": self.last_flow_reason,
                "source_point_count": metrics.source_point_count,
                "forward_valid_count": metrics.forward_valid_count,
                "retained_point_count": metrics.retained_point_count,
                "median_fb_error_px": metrics.median_fb_error_px,
                "fb_threshold_px": metrics.fb_threshold_px,
                "scale": metrics.scale,
                "rotation_degrees": metrics.rotation_degrees,
                "transform_model": metrics.transform_model,
                "reseeded": metrics.reseeded,
            },
            extra_metadata={
                "opencv_version": cv2.__version__,
                "flow_engine": "pyramidal_lucas_kanade",
                "feature_strategy": self.config.feature_strategy,
                "prediction_command_eligible": False,
            },
        )

    def get_capabilities(self) -> dict:
        capabilities = super().get_capabilities()
        capabilities.update(
            {
                "tracker_algorithm": "SparseFlow",
                "supports_rotation": True,
                "supports_scale_change": True,
                "supports_occlusion": False,
                "accuracy_rating": "scenario_dependent",
                "speed_rating": "scenario_dependent",
                "opencv_tracker": False,
                "flow_engine": "pyramidal_lucas_kanade",
                "forward_backward_validation": True,
                "appearance_revalidation": True,
                "adaptive_point_reseeding": True,
                "prediction_command_eligible": False,
            }
        )
        return capabilities
