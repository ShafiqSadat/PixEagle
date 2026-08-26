"""Reusable sparse optical-flow measurement core.

The core deliberately has no PixEagle lifecycle, estimator, detector, or
follower knowledge. It proposes one frame-to-frame measurement and advances its
accepted state only when the owning tracker calls :meth:`commit`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Mapping, Optional, Tuple

import cv2
import numpy as np


BBox = Tuple[int, int, int, int]


def _number(mapping: Mapping[str, Any], key: str) -> float:
    if key not in mapping:
        raise ValueError(f"SparseFlow_Tracker is missing required setting: {key}")
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"SparseFlow_Tracker.{key} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"SparseFlow_Tracker.{key} must be finite")
    return numeric


def _integer(mapping: Mapping[str, Any], key: str) -> int:
    value = _number(mapping, key)
    integer = int(value)
    if value != integer:
        raise ValueError(f"SparseFlow_Tracker.{key} must be an integer")
    return integer


def _bounded(value: float, key: str, minimum: float, maximum: float) -> float:
    if not minimum <= value <= maximum:
        raise ValueError(
            f"SparseFlow_Tracker.{key} must be within [{minimum}, {maximum}]"
        )
    return value


@dataclass(frozen=True)
class SparseFlowConfig:
    """Validated algorithm parameters loaded from the canonical YAML config."""

    feature_strategy: str
    max_points: int
    min_points: int
    quality_level: float
    min_distance_ratio: float
    roi_inset_ratio: float
    lk_window_size: int
    lk_max_level: int
    lk_max_iterations: int
    lk_epsilon: float
    fb_error_ratio: float
    fb_error_min_px: float
    fb_error_max_px: float
    ransac_reproj_ratio: float
    ransac_reproj_min_px: float
    ransac_reproj_max_px: float
    ransac_max_iterations: int
    ransac_confidence: float
    ransac_refine_iterations: int
    min_inlier_ratio: float
    max_scale_change_per_frame: float
    max_rotation_degrees_per_frame: float
    min_appearance_confidence: float
    confidence_threshold: float
    point_retention_weight: float
    flow_consistency_weight: float
    geometry_weight: float
    appearance_weight: float
    template_size: int
    template_update_alpha: float
    template_update_min_confidence: float
    initial_template_weight: float
    reseed_interval_frames: int
    reseed_below_ratio: float
    failure_threshold: int

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "SparseFlowConfig":
        if not isinstance(mapping, Mapping):
            raise ValueError("SparseFlow_Tracker configuration must be a mapping")

        if "feature_strategy" not in mapping:
            raise ValueError(
                "SparseFlow_Tracker is missing required setting: feature_strategy"
            )
        feature_strategy = str(mapping["feature_strategy"]).strip().lower()
        if feature_strategy not in {"auto", "gftt", "grid"}:
            raise ValueError(
                "SparseFlow_Tracker.feature_strategy must be auto, gftt, or grid"
            )

        max_points = _integer(mapping, "max_points")
        min_points = _integer(mapping, "min_points")
        if not 4 <= max_points <= 2000:
            raise ValueError(
                "SparseFlow_Tracker.max_points must be between 4 and 2000"
            )
        if min_points < 3 or min_points > max_points:
            raise ValueError(
                "SparseFlow_Tracker.min_points must be between 3 and max_points"
            )

        lk_window_size = _integer(mapping, "lk_window_size")
        if lk_window_size < 5 or lk_window_size % 2 == 0:
            raise ValueError(
                "SparseFlow_Tracker.lk_window_size must be an odd integer >= 5"
            )

        weights = {
            "point_retention_weight": _number(mapping, "point_retention_weight"),
            "flow_consistency_weight": _number(mapping, "flow_consistency_weight"),
            "geometry_weight": _number(mapping, "geometry_weight"),
            "appearance_weight": _number(mapping, "appearance_weight"),
        }
        if (
            any(not 0.0 <= value <= 1.0 for value in weights.values())
            or sum(weights.values()) <= 0.0
        ):
            raise ValueError(
                "SparseFlow_Tracker confidence weights must be within [0, 1] with a positive sum"
            )

        return cls(
            feature_strategy=feature_strategy,
            max_points=max_points,
            min_points=min_points,
            quality_level=_bounded(
                _number(mapping, "quality_level"), "quality_level", 1e-6, 1.0
            ),
            min_distance_ratio=_bounded(
                _number(mapping, "min_distance_ratio"),
                "min_distance_ratio",
                0.0,
                1.0,
            ),
            roi_inset_ratio=_bounded(
                _number(mapping, "roi_inset_ratio"), "roi_inset_ratio", 0.0, 0.45
            ),
            lk_window_size=lk_window_size,
            lk_max_level=int(
                _bounded(
                    _integer(mapping, "lk_max_level"), "lk_max_level", 0, 8
                )
            ),
            lk_max_iterations=int(
                _bounded(
                    _integer(mapping, "lk_max_iterations"),
                    "lk_max_iterations",
                    1,
                    200,
                )
            ),
            lk_epsilon=_bounded(
                _number(mapping, "lk_epsilon"), "lk_epsilon", 1e-6, 1.0
            ),
            fb_error_ratio=_bounded(
                _number(mapping, "fb_error_ratio"), "fb_error_ratio", 0.0, 1.0
            ),
            fb_error_min_px=_bounded(
                _number(mapping, "fb_error_min_px"), "fb_error_min_px", 0.0, 100.0
            ),
            fb_error_max_px=_bounded(
                _number(mapping, "fb_error_max_px"), "fb_error_max_px", 0.0, 500.0
            ),
            ransac_reproj_ratio=_bounded(
                _number(mapping, "ransac_reproj_ratio"),
                "ransac_reproj_ratio",
                0.0,
                1.0,
            ),
            ransac_reproj_min_px=_bounded(
                _number(mapping, "ransac_reproj_min_px"),
                "ransac_reproj_min_px",
                0.01,
                100.0,
            ),
            ransac_reproj_max_px=_bounded(
                _number(mapping, "ransac_reproj_max_px"),
                "ransac_reproj_max_px",
                0.01,
                500.0,
            ),
            ransac_max_iterations=int(
                _bounded(
                    _integer(mapping, "ransac_max_iterations"),
                    "ransac_max_iterations",
                    1,
                    10000,
                )
            ),
            ransac_confidence=_bounded(
                _number(mapping, "ransac_confidence"),
                "ransac_confidence",
                0.5,
                0.999999,
            ),
            ransac_refine_iterations=int(
                _bounded(
                    _integer(mapping, "ransac_refine_iterations"),
                    "ransac_refine_iterations",
                    0,
                    100,
                )
            ),
            min_inlier_ratio=_bounded(
                _number(mapping, "min_inlier_ratio"), "min_inlier_ratio", 0.0, 1.0
            ),
            max_scale_change_per_frame=_bounded(
                _number(mapping, "max_scale_change_per_frame"),
                "max_scale_change_per_frame",
                0.0,
                2.0,
            ),
            max_rotation_degrees_per_frame=_bounded(
                _number(mapping, "max_rotation_degrees_per_frame"),
                "max_rotation_degrees_per_frame",
                0.0,
                180.0,
            ),
            min_appearance_confidence=_bounded(
                _number(mapping, "min_appearance_confidence"),
                "min_appearance_confidence",
                0.0,
                1.0,
            ),
            confidence_threshold=_bounded(
                _number(mapping, "confidence_threshold"),
                "confidence_threshold",
                0.0,
                1.0,
            ),
            point_retention_weight=weights["point_retention_weight"],
            flow_consistency_weight=weights["flow_consistency_weight"],
            geometry_weight=weights["geometry_weight"],
            appearance_weight=weights["appearance_weight"],
            template_size=int(
                _bounded(
                    _integer(mapping, "template_size"), "template_size", 8, 256
                )
            ),
            template_update_alpha=_bounded(
                _number(mapping, "template_update_alpha"),
                "template_update_alpha",
                0.0,
                1.0,
            ),
            template_update_min_confidence=_bounded(
                _number(mapping, "template_update_min_confidence"),
                "template_update_min_confidence",
                0.0,
                1.0,
            ),
            initial_template_weight=_bounded(
                _number(mapping, "initial_template_weight"),
                "initial_template_weight",
                0.0,
                1.0,
            ),
            reseed_interval_frames=int(
                _bounded(
                    _integer(mapping, "reseed_interval_frames"),
                    "reseed_interval_frames",
                    0,
                    10000,
                )
            ),
            reseed_below_ratio=_bounded(
                _number(mapping, "reseed_below_ratio"),
                "reseed_below_ratio",
                0.0,
                1.0,
            ),
            failure_threshold=int(
                _bounded(
                    _integer(mapping, "failure_threshold"),
                    "failure_threshold",
                    1,
                    1000,
                )
            ),
        )._validate_ordered_bounds()

    def _validate_ordered_bounds(self) -> "SparseFlowConfig":
        if self.fb_error_min_px > self.fb_error_max_px:
            raise ValueError(
                "SparseFlow_Tracker.fb_error_min_px must not exceed fb_error_max_px"
            )
        if self.ransac_reproj_min_px > self.ransac_reproj_max_px:
            raise ValueError(
                "SparseFlow_Tracker.ransac_reproj_min_px must not exceed ransac_reproj_max_px"
            )
        return self

    @property
    def confidence_weight_sum(self) -> float:
        return (
            self.point_retention_weight
            + self.flow_consistency_weight
            + self.geometry_weight
            + self.appearance_weight
        )


@dataclass(frozen=True)
class SparseFlowMetrics:
    source_point_count: int = 0
    forward_valid_count: int = 0
    retained_point_count: int = 0
    inlier_ratio: float = 0.0
    median_fb_error_px: float = 0.0
    fb_threshold_px: float = 0.0
    appearance_confidence: float = 0.0
    scale: float = 1.0
    rotation_degrees: float = 0.0
    confidence: float = 0.0
    transform_model: str = "none"
    reseeded: bool = False


@dataclass(frozen=True)
class SparseFlowProposal:
    success: bool
    reason: str
    bbox: Optional[BBox]
    metrics: SparseFlowMetrics
    source_revision: int
    gray: Optional[np.ndarray] = None
    points: Optional[np.ndarray] = None
    appearance_patch: Optional[np.ndarray] = None


class SparseFlowCore:
    """Stateful, commit-gated sparse optical-flow measurement provider."""

    def __init__(self, config: SparseFlowConfig) -> None:
        self.config = config
        self._revision = 0
        self._accepted_frames = 0
        self._previous_gray: Optional[np.ndarray] = None
        self._points: Optional[np.ndarray] = None
        self._bbox: Optional[BBox] = None
        self._initial_template: Optional[np.ndarray] = None
        self._adaptive_template: Optional[np.ndarray] = None

    @property
    def initialized(self) -> bool:
        return (
            self._previous_gray is not None
            and self._points is not None
            and self._bbox is not None
        )

    @property
    def point_count(self) -> int:
        return 0 if self._points is None else int(len(self._points))

    @property
    def bbox(self) -> Optional[BBox]:
        return self._bbox

    def reset(self) -> None:
        self._revision += 1
        self._accepted_frames = 0
        self._previous_gray = None
        self._points = None
        self._bbox = None
        self._initial_template = None
        self._adaptive_template = None

    def initialize(self, frame: np.ndarray, bbox: BBox) -> BBox:
        gray = self._to_gray(frame)
        clipped_bbox = self._clip_bbox(bbox, gray.shape)
        if clipped_bbox is None:
            raise ValueError("Sparse Flow requires a positive ROI overlapping the frame")

        points = self._seed_points(gray, clipped_bbox)
        if len(points) < self.config.min_points:
            raise ValueError(
                "Sparse Flow could not find enough trackable points; select a larger or more textured target"
            )

        template = self._extract_patch(gray, clipped_bbox)
        if template is None:
            raise ValueError("Sparse Flow could not initialize the target appearance")

        self._revision += 1
        self._accepted_frames = 0
        self._previous_gray = gray.copy()
        self._points = points.copy()
        self._bbox = clipped_bbox
        self._initial_template = template.copy()
        self._adaptive_template = template.copy()
        return clipped_bbox

    def propose(self, frame: np.ndarray) -> SparseFlowProposal:
        if not self.initialized:
            return self._failure("not_initialized")

        try:
            gray = self._to_gray(frame)
        except ValueError:
            return self._failure("invalid_frame")

        previous_gray = self._previous_gray
        previous_points = self._points
        previous_bbox = self._bbox
        if (
            previous_gray is None
            or previous_points is None
            or previous_bbox is None
        ):
            return self._failure("not_initialized")
        if gray.shape != previous_gray.shape:
            return self._failure("frame_shape_changed")

        lk_params = {
            "winSize": (self.config.lk_window_size, self.config.lk_window_size),
            "maxLevel": self.config.lk_max_level,
            "criteria": (
                cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                self.config.lk_max_iterations,
                self.config.lk_epsilon,
            ),
        }
        try:
            next_points, forward_status, _forward_error = cv2.calcOpticalFlowPyrLK(
                previous_gray,
                gray,
                previous_points,
                None,
                **lk_params,
            )
            if next_points is None or forward_status is None:
                return self._failure("forward_flow_failed")
            reverse_points, reverse_status, _reverse_error = cv2.calcOpticalFlowPyrLK(
                gray,
                previous_gray,
                next_points,
                None,
                **lk_params,
            )
        except cv2.error:
            return self._failure("optical_flow_error")

        if reverse_points is None or reverse_status is None:
            return self._failure("reverse_flow_failed")

        old_flat = previous_points.reshape(-1, 2)
        new_flat = next_points.reshape(-1, 2)
        reverse_flat = reverse_points.reshape(-1, 2)
        forward_valid = forward_status.reshape(-1).astype(bool)
        reverse_valid = reverse_status.reshape(-1).astype(bool)
        finite = (
            np.all(np.isfinite(old_flat), axis=1)
            & np.all(np.isfinite(new_flat), axis=1)
            & np.all(np.isfinite(reverse_flat), axis=1)
        )
        frame_height, frame_width = gray.shape
        in_frame = (
            (new_flat[:, 0] >= 0.0)
            & (new_flat[:, 0] < float(frame_width))
            & (new_flat[:, 1] >= 0.0)
            & (new_flat[:, 1] < float(frame_height))
        )
        forward_count = int(np.count_nonzero(forward_valid & finite & in_frame))

        bbox_diagonal = max(1.0, math.hypot(previous_bbox[2], previous_bbox[3]))
        fb_threshold = float(
            np.clip(
                self.config.fb_error_ratio * bbox_diagonal,
                self.config.fb_error_min_px,
                self.config.fb_error_max_px,
            )
        )
        fb_error = np.linalg.norm(old_flat - reverse_flat, axis=1)
        valid = (
            forward_valid
            & reverse_valid
            & finite
            & in_frame
            & (fb_error <= fb_threshold)
        )
        filtered_old = old_flat[valid]
        filtered_new = new_flat[valid]
        filtered_fb = fb_error[valid]
        if len(filtered_new) < self.config.min_points:
            return self._failure(
                "insufficient_consistent_points",
                SparseFlowMetrics(
                    source_point_count=len(old_flat),
                    forward_valid_count=forward_count,
                    retained_point_count=len(filtered_new),
                    median_fb_error_px=(
                        float(np.median(filtered_fb)) if len(filtered_fb) else 0.0
                    ),
                    fb_threshold_px=fb_threshold,
                ),
            )

        reprojection_threshold = float(
            np.clip(
                self.config.ransac_reproj_ratio * bbox_diagonal,
                self.config.ransac_reproj_min_px,
                self.config.ransac_reproj_max_px,
            )
        )
        matrix, inlier_mask, transform_model = self._estimate_transform(
            filtered_old,
            filtered_new,
            reprojection_threshold,
        )
        if matrix is None or inlier_mask is None:
            return self._failure("transform_estimation_failed")

        inlier_mask = inlier_mask.reshape(-1).astype(bool)
        inlier_count = int(np.count_nonzero(inlier_mask))
        inlier_ratio = inlier_count / max(1, len(filtered_new))
        if (
            inlier_count < self.config.min_points
            or inlier_ratio < self.config.min_inlier_ratio
        ):
            return self._failure(
                "insufficient_geometry_consensus",
                SparseFlowMetrics(
                    source_point_count=len(old_flat),
                    forward_valid_count=forward_count,
                    retained_point_count=inlier_count,
                    inlier_ratio=inlier_ratio,
                    median_fb_error_px=float(np.median(filtered_fb)),
                    fb_threshold_px=fb_threshold,
                    transform_model=transform_model,
                ),
            )

        scale = float(math.hypot(float(matrix[0, 0]), float(matrix[1, 0])))
        rotation_degrees = float(
            math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0])))
        )
        if not math.isfinite(scale) or scale <= 0.0:
            return self._failure("invalid_scale")
        if abs(scale - 1.0) > self.config.max_scale_change_per_frame:
            return self._failure("scale_invalid")
        if abs(rotation_degrees) > self.config.max_rotation_degrees_per_frame:
            return self._failure("rotation_invalid")

        candidate_bbox = self._transform_bbox(previous_bbox, matrix, scale)
        if not self._bbox_overlaps_frame(candidate_bbox, gray.shape):
            return self._failure("candidate_out_of_frame")

        appearance_patch = self._extract_patch(gray, candidate_bbox)
        if appearance_patch is None:
            return self._failure("appearance_patch_unavailable")
        appearance_confidence = self._appearance_confidence(appearance_patch)

        inlier_fb = filtered_fb[inlier_mask]
        median_fb_error = float(np.median(inlier_fb)) if len(inlier_fb) else fb_threshold
        point_retention = inlier_count / max(1, len(old_flat))
        flow_consistency = float(
            np.clip(1.0 - (median_fb_error / max(fb_threshold, 1e-6)), 0.0, 1.0)
        )
        confidence = self._weighted_confidence(
            point_retention=point_retention,
            flow_consistency=flow_consistency,
            geometry=inlier_ratio,
            appearance=appearance_confidence,
        )

        metrics = SparseFlowMetrics(
            source_point_count=len(old_flat),
            forward_valid_count=forward_count,
            retained_point_count=inlier_count,
            inlier_ratio=inlier_ratio,
            median_fb_error_px=median_fb_error,
            fb_threshold_px=fb_threshold,
            appearance_confidence=appearance_confidence,
            scale=scale,
            rotation_degrees=rotation_degrees,
            confidence=confidence,
            transform_model=transform_model,
        )
        if appearance_confidence < self.config.min_appearance_confidence:
            return self._failure("appearance_mismatch", metrics, candidate_bbox)

        committed_points = filtered_new[inlier_mask].reshape(-1, 1, 2).astype(np.float32)
        should_reseed = (
            len(committed_points) < self.config.max_points * self.config.reseed_below_ratio
            or (
                self.config.reseed_interval_frames > 0
                and (self._accepted_frames + 1) % self.config.reseed_interval_frames == 0
            )
        )
        if should_reseed:
            reseeded_points = self._seed_points(
                gray,
                candidate_bbox,
                existing=committed_points,
            )
            if len(reseeded_points) >= self.config.min_points:
                committed_points = reseeded_points
                metrics = replace(metrics, reseeded=True)

        return SparseFlowProposal(
            success=True,
            reason="measurement",
            bbox=candidate_bbox,
            metrics=metrics,
            source_revision=self._revision,
            gray=gray,
            points=committed_points,
            appearance_patch=appearance_patch,
        )

    def commit(self, proposal: SparseFlowProposal, accepted_confidence: float) -> None:
        if not proposal.success:
            raise ValueError("Cannot commit an unsuccessful Sparse Flow proposal")
        if proposal.source_revision != self._revision:
            raise RuntimeError("Sparse Flow proposal no longer matches accepted state")
        if (
            proposal.bbox is None
            or proposal.gray is None
            or proposal.points is None
            or proposal.appearance_patch is None
        ):
            raise ValueError("Sparse Flow proposal is incomplete")

        try:
            confidence = float(accepted_confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("Accepted Sparse Flow confidence must be numeric") from exc
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError(
                "Accepted Sparse Flow confidence must be finite and within [0, 1]"
            )

        next_template = self._adaptive_template
        if next_template is None:
            raise RuntimeError("Sparse Flow appearance state is not initialized")
        if confidence >= self.config.template_update_min_confidence:
            alpha = self.config.template_update_alpha
            next_template = (
                (1.0 - alpha) * next_template
                + alpha * proposal.appearance_patch
            ).astype(np.float32)

        # Publish all accepted state only after validation and template
        # preparation have completed successfully.
        self._previous_gray = proposal.gray.copy()
        self._points = proposal.points.copy()
        self._bbox = proposal.bbox
        self._adaptive_template = next_template
        self._accepted_frames += 1
        self._revision += 1

    def _failure(
        self,
        reason: str,
        metrics: Optional[SparseFlowMetrics] = None,
        bbox: Optional[BBox] = None,
    ) -> SparseFlowProposal:
        return SparseFlowProposal(
            success=False,
            reason=reason,
            bbox=bbox,
            metrics=metrics or SparseFlowMetrics(),
            source_revision=self._revision,
        )

    @staticmethod
    def _to_gray(frame: np.ndarray) -> np.ndarray:
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8:
            raise ValueError("Sparse Flow requires an 8-bit NumPy frame")
        if frame.ndim == 2:
            gray = frame
        elif frame.ndim == 3 and frame.shape[2] == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        elif frame.ndim == 3 and frame.shape[2] == 4:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        else:
            raise ValueError("Sparse Flow requires grayscale, BGR, or BGRA frames")
        if gray.size == 0:
            raise ValueError("Sparse Flow frame is empty")
        return np.ascontiguousarray(gray)

    @staticmethod
    def _clip_bbox(bbox: Any, frame_shape: Tuple[int, int]) -> Optional[BBox]:
        if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
            return None
        try:
            x, y, width, height = (float(value) for value in bbox)
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in (x, y, width, height)):
            return None
        if width <= 1.0 or height <= 1.0:
            return None
        frame_height, frame_width = frame_shape[:2]
        x1 = max(0, int(math.floor(x)))
        y1 = max(0, int(math.floor(y)))
        x2 = min(frame_width, int(math.ceil(x + width)))
        y2 = min(frame_height, int(math.ceil(y + height)))
        if x2 - x1 < 2 or y2 - y1 < 2:
            return None
        return (x1, y1, x2 - x1, y2 - y1)

    @staticmethod
    def _bbox_overlaps_frame(bbox: BBox, frame_shape: Tuple[int, int]) -> bool:
        frame_height, frame_width = frame_shape[:2]
        x, y, width, height = bbox
        return (
            width > 1
            and height > 1
            and min(frame_width, x + width) > max(0, x)
            and min(frame_height, y + height) > max(0, y)
        )

    def _seed_points(
        self,
        gray: np.ndarray,
        bbox: BBox,
        existing: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        frame_height, frame_width = gray.shape
        x, y, width, height = bbox
        inset = int(round(min(width, height) * self.config.roi_inset_ratio))
        inset = min(inset, max(0, (width - 2) // 2), max(0, (height - 2) // 2))
        x1, y1 = max(0, x + inset), max(0, y + inset)
        x2 = min(frame_width, x + width - inset)
        y2 = min(frame_height, y + height - inset)
        if x2 - x1 < 2 or y2 - y1 < 2:
            return np.empty((0, 1, 2), dtype=np.float32)

        minimum_distance = max(
            1.0,
            self.config.min_distance_ratio * math.hypot(width, height),
        )
        selected = []
        if existing is not None:
            for point in existing.reshape(-1, 2):
                if (
                    np.all(np.isfinite(point))
                    and x1 <= float(point[0]) < x2
                    and y1 <= float(point[1]) < y2
                ):
                    selected.append(np.asarray(point, dtype=np.float32))
                    if len(selected) >= self.config.max_points:
                        break

        mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
        mask[y1:y2, x1:x2] = 255
        for point in selected:
            cv2.circle(
                mask,
                (int(round(float(point[0]))), int(round(float(point[1])))),
                int(math.ceil(minimum_distance)),
                0,
                -1,
            )

        remaining = self.config.max_points - len(selected)
        if remaining > 0 and self.config.feature_strategy in {"auto", "gftt"}:
            corners = cv2.goodFeaturesToTrack(
                gray,
                maxCorners=remaining,
                qualityLevel=self.config.quality_level,
                minDistance=minimum_distance,
                mask=mask,
                blockSize=3,
                useHarrisDetector=False,
            )
            if corners is not None:
                for point in corners.reshape(-1, 2):
                    selected.append(np.asarray(point, dtype=np.float32))
                    if len(selected) >= self.config.max_points:
                        break

        if (
            len(selected) < self.config.max_points
            and self.config.feature_strategy in {"auto", "grid"}
        ):
            target_count = self.config.max_points - len(selected)
            aspect = max((x2 - x1) / max(1.0, float(y2 - y1)), 1e-6)
            columns = max(1, int(math.ceil(math.sqrt(target_count * aspect))))
            rows = max(1, int(math.ceil(target_count / columns)))
            grid_x = np.linspace(x1 + 0.5, x2 - 0.5, columns)
            grid_y = np.linspace(y1 + 0.5, y2 - 0.5, rows)
            for point_y in grid_y:
                for point_x in grid_x:
                    candidate = np.asarray((point_x, point_y), dtype=np.float32)
                    if all(
                        float(np.linalg.norm(candidate - current)) >= minimum_distance
                        for current in selected
                    ):
                        selected.append(candidate)
                    if len(selected) >= self.config.max_points:
                        break
                if len(selected) >= self.config.max_points:
                    break

        if not selected:
            return np.empty((0, 1, 2), dtype=np.float32)
        return np.asarray(selected[: self.config.max_points], dtype=np.float32).reshape(-1, 1, 2)

    def _extract_patch(self, gray: np.ndarray, bbox: BBox) -> Optional[np.ndarray]:
        clipped = self._clip_bbox(bbox, gray.shape)
        if clipped is None:
            return None
        x, y, width, height = clipped
        crop = gray[y : y + height, x : x + width]
        if crop.size == 0:
            return None
        interpolation = (
            cv2.INTER_AREA
            if width > self.config.template_size or height > self.config.template_size
            else cv2.INTER_LINEAR
        )
        return cv2.resize(
            crop,
            (self.config.template_size, self.config.template_size),
            interpolation=interpolation,
        ).astype(np.float32)

    @staticmethod
    def _normalized_correlation(first: np.ndarray, second: np.ndarray) -> float:
        first_centered = first.astype(np.float32) - float(np.mean(first))
        second_centered = second.astype(np.float32) - float(np.mean(second))
        first_norm = float(np.linalg.norm(first_centered))
        second_norm = float(np.linalg.norm(second_centered))
        if first_norm <= 1e-6 or second_norm <= 1e-6:
            mean_delta = abs(float(np.mean(first)) - float(np.mean(second)))
            return 1.0 if mean_delta <= 1.0 else 0.0
        correlation = float(
            np.sum(first_centered * second_centered) / (first_norm * second_norm)
        )
        return float(np.clip(correlation, 0.0, 1.0))

    def _appearance_confidence(self, patch: np.ndarray) -> float:
        if self._initial_template is None or self._adaptive_template is None:
            return 0.0
        initial_score = self._normalized_correlation(patch, self._initial_template)
        adaptive_score = self._normalized_correlation(patch, self._adaptive_template)
        weight = self.config.initial_template_weight
        return float(np.clip(weight * initial_score + (1.0 - weight) * adaptive_score, 0.0, 1.0))

    def _estimate_transform(
        self,
        old_points: np.ndarray,
        new_points: np.ndarray,
        reprojection_threshold: float,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], str]:
        try:
            matrix, inliers = cv2.estimateAffinePartial2D(
                old_points,
                new_points,
                method=cv2.RANSAC,
                ransacReprojThreshold=reprojection_threshold,
                maxIters=self.config.ransac_max_iterations,
                confidence=self.config.ransac_confidence,
                refineIters=self.config.ransac_refine_iterations,
            )
        except cv2.error:
            matrix, inliers = None, None

        if matrix is not None and inliers is not None and np.all(np.isfinite(matrix)):
            return matrix.astype(np.float64), inliers, "partial_affine_ransac"

        displacement = new_points - old_points
        translation = np.median(displacement, axis=0)
        residual = np.linalg.norm(displacement - translation, axis=1)
        inliers = (residual <= reprojection_threshold).astype(np.uint8).reshape(-1, 1)
        matrix = np.asarray(
            [[1.0, 0.0, translation[0]], [0.0, 1.0, translation[1]]],
            dtype=np.float64,
        )
        return matrix, inliers, "median_translation_fallback"

    @staticmethod
    def _transform_bbox(bbox: BBox, matrix: np.ndarray, scale: float) -> BBox:
        x, y, width, height = bbox
        center = np.asarray((x + width / 2.0, y + height / 2.0, 1.0))
        transformed_center = matrix @ center
        next_width = max(2, int(round(width * scale)))
        next_height = max(2, int(round(height * scale)))
        return (
            int(round(float(transformed_center[0]) - next_width / 2.0)),
            int(round(float(transformed_center[1]) - next_height / 2.0)),
            next_width,
            next_height,
        )

    def _weighted_confidence(
        self,
        *,
        point_retention: float,
        flow_consistency: float,
        geometry: float,
        appearance: float,
    ) -> float:
        weighted = (
            self.config.point_retention_weight * point_retention
            + self.config.flow_consistency_weight * flow_consistency
            + self.config.geometry_weight * geometry
            + self.config.appearance_weight * appearance
        )
        return float(np.clip(weighted / self.config.confidence_weight_sum, 0.0, 1.0))
