# src/classes/detectors/template_matching_detector.py

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .base_detector import BaseDetector
from classes.parameters import Parameters
from classes.tracking_recovery import (
    RecoveryCandidate,
    RecoveryDetectionResult,
    RecoverySearchRequirements,
)
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TemplateMatchCandidate:
    bbox: Tuple[int, int, int, int]
    match_confidence: float
    raw_score: float
    template_source: str

class TemplateMatchingDetector(BaseDetector):
    """
    TemplateMatchingDetector Class

    Implements object detection using OpenCV's template matching methods with improvements
    for robust redetection.
    """

    def __init__(self):
        """
        Initializes the TemplateMatchingDetector with the specified matching method.
        """
        super().__init__()
        self.template: Optional[np.ndarray] = None
        self.trusted_template: Optional[np.ndarray] = None
        self.trusted_features: Optional[np.ndarray] = None
        self.latest_bbox: Optional[Tuple[int, int, int, int]] = None
        self.method = self.get_matching_method(Parameters.TEMPLATE_MATCHING_METHOD)
        self.initial_features: Optional[np.ndarray] = None
        self.adaptive_features: Optional[np.ndarray] = None
        self.latest_match_score: Optional[float] = None
        self.latest_template_source: Optional[str] = None

    @staticmethod
    def get_matching_method(method_name: str):
        """
        Maps the method name to the corresponding OpenCV template matching method.

        Args:
            method_name (str): Name of the template matching method.

        Returns:
            int: OpenCV method constant.
        """
        methods = {
            "TM_CCOEFF": cv2.TM_CCOEFF,
            "TM_CCOEFF_NORMED": cv2.TM_CCOEFF_NORMED,
            "TM_CCORR": cv2.TM_CCORR,
            "TM_CCORR_NORMED": cv2.TM_CCORR_NORMED,
            "TM_SQDIFF": cv2.TM_SQDIFF,
            "TM_SQDIFF_NORMED": cv2.TM_SQDIFF_NORMED,
        }
        return methods.get(method_name, cv2.TM_CCOEFF_NORMED)

    def extract_features(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> np.ndarray:
        """
        Extracts features and initializes the template and adaptive features if not already set.

        Args:
            frame (np.ndarray): The current video frame.
            bbox (Tuple[int, int, int, int]): Bounding box (x, y, w, h).

        Returns:
            np.ndarray: The feature vector.
        """
        features = super().extract_features(frame, bbox)
        x, y, w, h = bbox

        # Initialize the template only once
        if self.template is None:
            self.template = frame[y:y+h, x:x+w].copy()
            self.initial_template = self.template.copy()
            self.trusted_template = self.template.copy()
            logger.debug("Template extracted and set for template matching.")

        # Initialize features if not set
        if self.initial_features is None:
            self.initial_features = features.copy()
            self.adaptive_features = features.copy()
            self.trusted_features = features.copy()
            logger.debug("Initial features set for template matching.")

        self.latest_bbox = bbox
        return features

    def initialize_target(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
    ) -> np.ndarray:
        """Replace every identity baseline when the operator selects a target."""
        normalized_bbox, roi = self._validated_target_roi(frame, bbox)
        features = BaseDetector.extract_features(self, frame, normalized_bbox)
        self.template = roi.copy()
        self.initial_template = roi.copy()
        self.trusted_template = roi.copy()
        self.initial_features = features.copy()
        self.adaptive_features = features.copy()
        self.trusted_features = features.copy()
        self.latest_bbox = normalized_bbox
        self.latest_match_score = None
        self.latest_template_source = None
        return features

    def update_template(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> None:
        """
        Updates the adaptive features based on the current frame.

        Args:
            frame (np.ndarray): The current video frame.
            bbox (Tuple[int, int, int, int]): Bounding box (x, y, w, h).
        """
        try:
            normalized_bbox, roi = self._validated_target_roi(frame, bbox)
        except (TypeError, ValueError):
            logger.debug("Skipped trusted recovery view outside the current frame")
            return
        features = BaseDetector.extract_features(self, frame, normalized_bbox)
        learning_rate = float(Parameters.TEMPLATE_APPEARANCE_LEARNING_RATE)
        learning_rate = min(max(learning_rate, 0.0), 1.0)
        if self.adaptive_features is None:
            self.adaptive_features = features.copy()
        else:
            self.adaptive_features = (
                (1.0 - learning_rate) * self.adaptive_features
                + learning_rate * features
            )
        # The immutable initial template protects identity; this trusted recent
        # view supplies a second appearance/background condition for recovery.
        self.trusted_template = roi.copy()
        self.trusted_features = features.copy()
        logger.debug(
            "TEMPLATE: Trusted recovery view updated (learning rate %.4f)",
            learning_rate,
        )

    def get_recovery_search_requirements(self) -> RecoverySearchRequirements:
        templates = self._recovery_templates()
        if not templates:
            return super().get_recovery_search_requirements()
        return RecoverySearchRequirements(
            min_width=max(template.shape[1] for _, template in templates),
            min_height=max(template.shape[0] for _, template in templates),
        )

    def snapshot_identity_state(self) -> Dict[str, Any]:
        state = super().snapshot_identity_state()
        for name in ("template", "trusted_template", "trusted_features"):
            value = getattr(self, name, None)
            state[name] = value.copy() if isinstance(value, np.ndarray) else value
        return state

    def restore_identity_state(self, state: Dict[str, Any]) -> None:
        super().restore_identity_state(state)
        for name in ("template", "trusted_template", "trusted_features"):
            value = state.get(name)
            setattr(
                self,
                name,
                value.copy() if isinstance(value, np.ndarray) else value,
            )

    def smart_redetection(
        self,
        frame: np.ndarray,
        tracker=None,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> bool:
        """Compatibility adapter for callers that still consume a boolean."""
        return self.propose_recovery(frame, tracker=tracker, roi=roi).accepted

    def propose_recovery(
        self,
        frame: np.ndarray,
        tracker=None,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> RecoveryDetectionResult:
        """Return a unique appearance-validated candidate without changing identity."""
        del tracker  # Recovery motion/locality is owned by the shared search plan.
        if self.template is None:
            logger.warning("Template has not been set.")
            return RecoveryDetectionResult(False, "target_template_unavailable")

        prepared_region = self.prepare_recovery_search_region(
            frame,
            roi,
            self.get_recovery_search_requirements(),
        )
        if prepared_region is None:
            logger.warning(
                "Rejected invalid or undersized re-detection search region: %s",
                roi,
            )
            return RecoveryDetectionResult(False, "invalid_search_region")
        frame_to_search, x_offset, y_offset = prepared_region

        matches = self._find_template_match_candidates(frame_to_search)
        validated: List[RecoveryCandidate] = []
        appearance_threshold = self._finite_unit_parameter(
            getattr(Parameters, "APPEARANCE_CONFIDENCE_THRESHOLD", 0.7),
            fallback=0.7,
        )
        for match in matches:
            x, y, width, height = match.bbox
            bbox = (x + x_offset, y + y_offset, width, height)
            appearance_confidence = self._appearance_confidence(frame, bbox)
            if appearance_confidence + 1e-6 < appearance_threshold:
                continue
            association_confidence = math.sqrt(
                max(0.0, match.match_confidence)
                * max(0.0, appearance_confidence)
            )
            validated.append(
                RecoveryCandidate(
                    bbox=bbox,
                    visual_confidence=match.match_confidence,
                    appearance_confidence=appearance_confidence,
                    association_confidence=association_confidence,
                    source=match.template_source,
                    raw_score=match.raw_score,
                )
            )

        validated.sort(
            key=lambda candidate: (
                candidate.association_confidence,
                candidate.visual_confidence,
                candidate.appearance_confidence,
            ),
            reverse=True,
        )
        if not validated:
            logger.debug("TEMPLATE: No appearance-validated recovery candidates")
            return RecoveryDetectionResult(False, "no_validated_candidate")

        best = validated[0]
        runner_up = validated[1] if len(validated) > 1 else None
        confidence_margin = (
            best.association_confidence - runner_up.association_confidence
            if runner_up is not None
            else None
        )
        minimum_margin = self._finite_unit_parameter(
            getattr(Parameters, "REDETECTION_MIN_CONFIDENCE_MARGIN", 0.05),
            fallback=0.05,
        )
        if (
            runner_up is not None
            and confidence_margin is not None
            and confidence_margin + 1e-6 < minimum_margin
        ):
            logger.warning(
                "TEMPLATE: Recovery remains ambiguous across %d candidates "
                "(best=%.3f, runner-up=%.3f, required margin=%.3f)",
                len(validated),
                best.association_confidence,
                runner_up.association_confidence,
                minimum_margin,
            )
            return RecoveryDetectionResult(
                accepted=False,
                reason="ambiguous_candidates",
                candidate_count=len(validated),
                ambiguous=True,
                runner_up_confidence=runner_up.association_confidence,
                confidence_margin=confidence_margin,
            )

        self.latest_bbox = best.bbox
        self.latest_match_score = best.raw_score
        self.latest_template_source = best.source
        logger.info(
            "TEMPLATE: Validated unique %s-template recovery at %s "
            "(identity=%.3f, candidates=%d)",
            best.source,
            best.bbox,
            best.association_confidence,
            len(validated),
        )
        return RecoveryDetectionResult(
            accepted=True,
            reason="unique_validated_candidate",
            candidate=best,
            candidate_count=len(validated),
            runner_up_confidence=(
                runner_up.association_confidence if runner_up is not None else None
            ),
            confidence_margin=confidence_margin,
        )

    def _recovery_templates(self) -> List[Tuple[str, np.ndarray]]:
        """Return immutable and trusted recent views without duplicate work."""
        templates: List[Tuple[str, np.ndarray]] = []
        initial = self.initial_template if self.initial_template is not None else self.template
        if isinstance(initial, np.ndarray) and initial.size:
            templates.append(("initial", initial))
        trusted = self.trusted_template
        if isinstance(trusted, np.ndarray) and trusted.size:
            if not templates or not np.array_equal(templates[0][1], trusted):
                templates.append(("trusted", trusted))
        return templates

    def perform_multiscale_template_matching(
        self,
        frame_to_search: np.ndarray,
    ) -> Tuple[bool, Tuple[int, int, int, int]]:
        """Compatibility view of the highest normalized candidate."""
        self.latest_match_score = None
        self.latest_template_source = None
        candidates = self._find_template_match_candidates(frame_to_search)
        if not candidates:
            return False, (0, 0, 0, 0)
        best = candidates[0]
        self.latest_match_score = best.raw_score
        self.latest_template_source = best.template_source
        return True, best.bbox

    @staticmethod
    def _finite_unit_parameter(value: object, *, fallback: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = fallback
        if not np.isfinite(parsed):
            parsed = fallback
        return float(np.clip(parsed, 0.0, 1.0))

    @staticmethod
    def _candidate_limit() -> int:
        try:
            return max(
                1,
                min(50, int(Parameters.REDETECTION_MAX_CANDIDATES)),
            )
        except (AttributeError, TypeError, ValueError):
            return 5

    @staticmethod
    def _normalized_method(method: int) -> int:
        return {
            cv2.TM_CCOEFF: cv2.TM_CCOEFF_NORMED,
            cv2.TM_CCORR: cv2.TM_CCORR_NORMED,
            cv2.TM_SQDIFF: cv2.TM_SQDIFF_NORMED,
        }.get(method, method)

    @staticmethod
    def _confidence_response(response: np.ndarray, method: int) -> np.ndarray:
        finite = np.asarray(response, dtype=np.float32)
        if method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
            return 1.0 - np.clip(finite, 0.0, 1.0)
        return np.clip(finite, 0.0, 1.0)

    def _score_is_accepted(self, raw_score: float) -> bool:
        if not np.isfinite(raw_score):
            return False
        try:
            threshold = float(Parameters.TEMPLATE_MATCHING_THRESHOLD)
        except (TypeError, ValueError):
            logger.error("Template matching threshold is not numeric")
            return False
        if not np.isfinite(threshold):
            logger.error("Template matching threshold is not finite")
            return False
        if self.method == cv2.TM_SQDIFF_NORMED:
            return raw_score <= 1.0 - np.clip(threshold, 0.0, 1.0) + 1e-6
        if self.method == cv2.TM_SQDIFF:
            return raw_score <= threshold + 1e-6
        return raw_score + 1e-6 >= threshold

    @staticmethod
    def _bbox_iou(
        first: Tuple[int, int, int, int],
        second: Tuple[int, int, int, int],
    ) -> float:
        first_x, first_y, first_width, first_height = first
        second_x, second_y, second_width, second_height = second
        intersection_width = max(
            0,
            min(first_x + first_width, second_x + second_width)
            - max(first_x, second_x),
        )
        intersection_height = max(
            0,
            min(first_y + first_height, second_y + second_height)
            - max(first_y, second_y),
        )
        intersection = intersection_width * intersection_height
        if intersection <= 0:
            return 0.0
        union = (
            first_width * first_height
            + second_width * second_height
            - intersection
        )
        return float(intersection / union) if union > 0 else 0.0

    def _response_candidates(
        self,
        raw_response: np.ndarray,
        confidence_response: np.ndarray,
        *,
        template_size: Tuple[int, int],
        template_source: str,
    ) -> List[_TemplateMatchCandidate]:
        """Extract bounded spatial peaks from one template/scale response."""
        width, height = template_size
        working = np.asarray(confidence_response, dtype=np.float32).copy()
        working[~np.isfinite(working)] = -np.inf
        candidates: List[_TemplateMatchCandidate] = []
        limit = self._candidate_limit()
        inspected = 0
        inspection_limit = max(limit, limit * 4)

        while working.size and inspected < inspection_limit:
            _, confidence, _, location = cv2.minMaxLoc(working)
            if not np.isfinite(confidence):
                break
            x, y = location
            raw_score = float(raw_response[y, x])
            if self._score_is_accepted(raw_score):
                candidates.append(
                    _TemplateMatchCandidate(
                        bbox=(x, y, width, height),
                        match_confidence=float(np.clip(confidence, 0.0, 1.0)),
                        raw_score=raw_score,
                        template_source=template_source,
                    )
                )
                if len(candidates) >= limit:
                    break

            inspected += 1
            x_radius = max(1, width // 2)
            y_radius = max(1, height // 2)
            x_start = max(0, x - x_radius)
            x_end = min(working.shape[1], x + x_radius + 1)
            y_start = max(0, y - y_radius)
            y_end = min(working.shape[0], y + y_radius + 1)
            working[y_start:y_end, x_start:x_end] = -np.inf

        return candidates

    def _deduplicate_candidates(
        self,
        candidates: List[_TemplateMatchCandidate],
    ) -> List[_TemplateMatchCandidate]:
        threshold = self._finite_unit_parameter(
            getattr(Parameters, "REDETECTION_CANDIDATE_NMS_IOU", 0.3),
            fallback=0.3,
        )
        candidates.sort(
            key=lambda candidate: candidate.match_confidence,
            reverse=True,
        )
        selected: List[_TemplateMatchCandidate] = []
        for candidate in candidates:
            duplicate = False
            for existing in selected:
                overlap = self._bbox_iou(candidate.bbox, existing.bbox)
                if overlap > 0.0 and overlap >= threshold:
                    duplicate = True
                    break
            if duplicate:
                continue
            selected.append(candidate)
            if len(selected) >= self._candidate_limit():
                break
        return selected

    def _find_template_match_candidates(
        self,
        frame_to_search: np.ndarray,
    ) -> List[_TemplateMatchCandidate]:
        candidates: List[_TemplateMatchCandidate] = []
        normalized_method = self._normalized_method(self.method)
        best_observed_confidence = -math.inf
        best_observed_score: Optional[float] = None
        best_observed_source: Optional[str] = None

        for template_source, template in self._recovery_templates():
            for scale in Parameters.TEMPLATE_MATCHING_SCALES:
                try:
                    scale_value = float(scale)
                except (TypeError, ValueError):
                    continue
                if not np.isfinite(scale_value) or scale_value <= 0.0:
                    continue
                interpolation = (
                    cv2.INTER_AREA if scale_value <= 1.0 else cv2.INTER_LINEAR
                )
                resized_template = cv2.resize(
                    template,
                    None,
                    fx=scale_value,
                    fy=scale_value,
                    interpolation=interpolation,
                )
                if (
                    resized_template.size == 0
                    or frame_to_search.shape[0] < resized_template.shape[0]
                    or frame_to_search.shape[1] < resized_template.shape[1]
                ):
                    continue

                raw_response = cv2.matchTemplate(
                    frame_to_search,
                    resized_template,
                    self.method,
                )
                if normalized_method == self.method:
                    normalized_response = raw_response
                else:
                    normalized_response = cv2.matchTemplate(
                        frame_to_search,
                        resized_template,
                        normalized_method,
                    )
                confidence_response = self._confidence_response(
                    normalized_response,
                    normalized_method,
                )
                _, observed_confidence, _, observed_location = cv2.minMaxLoc(
                    confidence_response
                )
                if (
                    np.isfinite(observed_confidence)
                    and observed_confidence > best_observed_confidence
                ):
                    observed_x, observed_y = observed_location
                    best_observed_confidence = float(observed_confidence)
                    best_observed_score = float(
                        raw_response[observed_y, observed_x]
                    )
                    best_observed_source = template_source
                candidates.extend(
                    self._response_candidates(
                        raw_response,
                        confidence_response,
                        template_size=(
                            int(resized_template.shape[1]),
                            int(resized_template.shape[0]),
                        ),
                        template_source=template_source,
                    )
                )

        self.latest_match_score = best_observed_score
        self.latest_template_source = best_observed_source
        return self._deduplicate_candidates(candidates)

    def validate_match(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> bool:
        """
        Validates the matched area by comparing appearance features.

        Args:
            frame (np.ndarray): The current video frame.
            bbox (Tuple[int, int, int, int]): Bounding box of the matched area.

        Returns:
            bool: True if the match is valid, False otherwise.
        """
        confidence = self._appearance_confidence(frame, bbox)
        logger.debug("Appearance confidence: %.2f", confidence)
        return confidence >= Parameters.APPEARANCE_CONFIDENCE_THRESHOLD

    def _appearance_confidence(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
    ) -> float:
        """Return the strongest bounded immutable/trusted appearance score."""
        current_features = BaseDetector.extract_features(self, frame, bbox)
        confidences = []
        if self.initial_features is not None:
            confidences.append(
                self.compute_appearance_confidence(
                    current_features,
                    self.initial_features,
                )
            )
        if self.adaptive_features is not None:
            confidences.append(
                self.compute_appearance_confidence(
                    current_features,
                    self.adaptive_features,
                )
            )
        if self.trusted_features is not None:
            confidences.append(
                self.compute_appearance_confidence(
                    current_features,
                    self.trusted_features,
                )
            )
        return max(confidences, default=0.0)

    def compute_appearance_confidence(self, features: np.ndarray, reference_features: np.ndarray) -> float:
        """
        Computes the appearance confidence between the current features and the reference features.

        Args:
            features (np.ndarray): The features from the current detection.
            reference_features (np.ndarray): The reference features to compare against.

        Returns:
            float: The confidence score between 0 and 1.
        """
        # Use cosine similarity as an example
        numerator = np.dot(features.flatten(), reference_features.flatten())
        denominator = np.linalg.norm(features.flatten()) * np.linalg.norm(reference_features.flatten())
        if denominator == 0:
            return 0.0
        else:
            confidence = float(numerator / denominator)
            if not np.isfinite(confidence):
                return 0.0
            if confidence < 0.0:
                return 0.0
            if confidence > 1.0:
                return 1.0 if confidence <= 1.0 + 1e-6 else 0.0
            return confidence

    def draw_detection(self, frame: np.ndarray, color=(0, 255, 255)) -> np.ndarray:
        """
        Draws the detection bounding box on the frame.

        Args:
            frame (np.ndarray): The current video frame.
            color (tuple): Color for the bounding box.

        Returns:
            np.ndarray: The frame with detection drawn.
        """
        if self.latest_bbox is None:
            return frame
        x, y, w, h = self.latest_bbox
        cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
        return frame

    def get_latest_bbox(self) -> Optional[Tuple[int, int, int, int]]:
        """
        Retrieves the latest bounding box from detection.

        Returns:
            Optional[Tuple[int, int, int, int]]: The latest bounding box or None.
        """
        return self.latest_bbox

    def set_latest_bbox(self, bbox: Tuple[int, int, int, int]) -> None:
        """
        Sets the latest bounding box for detection.

        Args:
            bbox (Tuple[int, int, int, int]): The bounding box to set.
        """
        self.latest_bbox = bbox
