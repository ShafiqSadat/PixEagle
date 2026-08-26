"""Shared, bounded search planning for classic tracker recovery.

Trackers provide motion/last-measurement hints, detectors provide their minimum
search dimensions, and the application owns the retry budget.  Keeping search
planning here prevents individual trackers from growing incompatible recovery
rules.
"""

from dataclasses import dataclass
import math
from typing import Optional, Sequence, Tuple


BoundingBox = Tuple[int, int, int, int]
Point = Tuple[float, float]


@dataclass(frozen=True)
class RecoveryHint:
    """Tracker-owned information that may guide, but never authorize, recovery."""

    predicted_center: Optional[Point] = None
    last_seen_bbox: Optional[BoundingBox] = None
    prediction_reliable: bool = False
    exit_edge: Optional[str] = None


@dataclass(frozen=True)
class RecoverySearchRequirements:
    """Minimum image dimensions required by a detector search."""

    min_width: int = 1
    min_height: int = 1


@dataclass(frozen=True)
class RecoverySearchPlan:
    """One deterministic search step within an application-owned retry budget."""

    roi: Optional[BoundingBox]
    scope: str
    anchor_source: str
    attempt: int
    max_attempts: int
    radius: Optional[int]


@dataclass(frozen=True)
class RecoveryCandidate:
    """One detector proposal that has passed its independent confidence gates."""

    bbox: BoundingBox
    visual_confidence: float
    appearance_confidence: float
    association_confidence: float
    source: str
    raw_score: Optional[float] = None


@dataclass(frozen=True)
class RecoveryDetectionResult:
    """Detector outcome before the application mutates tracker target state."""

    accepted: bool
    reason: str
    candidate: Optional[RecoveryCandidate] = None
    candidate_count: int = 0
    ambiguous: bool = False
    runner_up_confidence: Optional[float] = None
    confidence_margin: Optional[float] = None


def _finite_point(value: Optional[Sequence[float]]) -> Optional[Point]:
    if value is None or len(value) < 2:
        return None
    try:
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return (x, y)


def _valid_bbox(value: Optional[Sequence[float]]) -> Optional[BoundingBox]:
    if value is None or len(value) < 4:
        return None
    try:
        x, y, width, height = (int(round(float(item))) for item in value[:4])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return (x, y, width, height)


def _positive_int(value: object, fallback: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return max(1, parsed)


def _nonnegative_float(value: object, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed):
        return fallback
    return max(0.0, parsed)


def build_recovery_search_plan(
    *,
    frame_shape: Sequence[int],
    hint: RecoveryHint,
    requirements: RecoverySearchRequirements,
    attempt: int,
    max_attempts: int,
    min_local_radius: object,
    max_local_radius: object,
    uncertainty_scale_factor: object,
    global_search_attempts: object,
) -> RecoverySearchPlan:
    """Build a valid local-to-global detector search plan.

    Local searches are target-size aware and expand over their allotted retry
    steps.  The final configured attempts search the full image so a target that
    leaves the prediction window can still be reacquired.  An out-of-frame
    prediction is clamped to the nearest image edge instead of producing a
    negative or empty ROI.
    """

    if len(frame_shape) < 2:
        raise ValueError("Recovery planning requires an image-shaped frame")
    frame_height = _positive_int(frame_shape[0], 1)
    frame_width = _positive_int(frame_shape[1], 1)
    max_attempts = _positive_int(max_attempts, 1)
    attempt = int(attempt)
    if attempt < 1 or attempt > max_attempts:
        raise ValueError("Recovery attempt must be inside the retry budget")

    global_count = min(
        max_attempts,
        max(0, int(_nonnegative_float(global_search_attempts, 1.0))),
    )
    local_attempts = max_attempts - global_count
    if local_attempts == 0 or attempt > local_attempts:
        return RecoverySearchPlan(
            roi=None,
            scope="global",
            anchor_source="full_frame",
            attempt=attempt,
            max_attempts=max_attempts,
            radius=None,
        )

    predicted_center = _finite_point(hint.predicted_center)
    last_seen_bbox = _valid_bbox(hint.last_seen_bbox)
    if predicted_center is not None and hint.prediction_reliable:
        anchor = predicted_center
        anchor_source = "prediction"
    elif last_seen_bbox is not None:
        x, y, width, height = last_seen_bbox
        anchor = (x + width / 2.0, y + height / 2.0)
        anchor_source = "last_measurement"
    else:
        return RecoverySearchPlan(
            roi=None,
            scope="global",
            anchor_source="no_local_hint",
            attempt=attempt,
            max_attempts=max_attempts,
            radius=None,
        )

    required_width = min(
        frame_width,
        _positive_int(requirements.min_width, 1),
    )
    required_height = min(
        frame_height,
        _positive_int(requirements.min_height, 1),
    )
    target_extent = max(required_width, required_height)
    if last_seen_bbox is not None:
        target_extent = max(target_extent, last_seen_bbox[2], last_seen_bbox[3])

    minimum_radius = _positive_int(min_local_radius, 1)
    target_radius = int(
        math.ceil(
            target_extent
            * _nonnegative_float(uncertainty_scale_factor, 2.0)
        )
    )
    start_radius = max(minimum_radius, target_radius)
    end_radius = max(start_radius, _positive_int(max_local_radius, start_radius))
    if local_attempts > 1:
        progress = (attempt - 1) / (local_attempts - 1)
    else:
        progress = 1.0
    radius = int(round(start_radius + ((end_radius - start_radius) * progress)))

    center_x = min(max(anchor[0], 0.0), float(frame_width - 1))
    center_y = min(max(anchor[1], 0.0), float(frame_height - 1))
    desired_width = min(frame_width, max(required_width, radius * 2))
    desired_height = min(frame_height, max(required_height, radius * 2))

    if desired_width >= frame_width and desired_height >= frame_height:
        return RecoverySearchPlan(
            roi=None,
            scope="global",
            anchor_source=anchor_source,
            attempt=attempt,
            max_attempts=max_attempts,
            radius=radius,
        )

    x = int(round(center_x - (desired_width / 2.0)))
    y = int(round(center_y - (desired_height / 2.0)))
    x = min(max(0, x), frame_width - desired_width)
    y = min(max(0, y), frame_height - desired_height)

    return RecoverySearchPlan(
        roi=(x, y, desired_width, desired_height),
        scope="local",
        anchor_source=anchor_source,
        attempt=attempt,
        max_attempts=max_attempts,
        radius=radius,
    )
