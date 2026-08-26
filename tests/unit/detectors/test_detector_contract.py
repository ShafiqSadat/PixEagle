"""Contract tests for detector interfaces and factories."""

from unittest.mock import patch

import cv2
import numpy as np
import pytest

from classes.detectors.base_detector import BaseDetector
from classes.detectors.detector_factory import create_detector
from classes.detectors.template_matching_detector import TemplateMatchingDetector


pytestmark = [pytest.mark.unit, pytest.mark.detectors]


def test_base_detector_is_abstract():
    """BaseDetector must remain an abstract extension contract."""
    with pytest.raises(TypeError):
        BaseDetector()


def test_template_matching_detector_implements_base_contract():
    """TemplateMatchingDetector should implement the detector base contract."""
    detector = TemplateMatchingDetector()

    assert isinstance(detector, BaseDetector)
    assert detector.get_latest_bbox() is None

    bbox = (2, 3, 4, 5)
    detector.set_latest_bbox(bbox)

    assert detector.get_latest_bbox() == bbox


def test_template_matching_detector_extracts_feature_vector():
    """Feature extraction should return the expected color histogram vector."""
    detector = TemplateMatchingDetector()
    frame = np.zeros((20, 20, 3), dtype=np.uint8)

    features = detector.extract_features(frame, (0, 0, 10, 10))

    assert features.shape == (16 * 16 * 16,)
    assert features.dtype == np.float32
    assert detector.get_latest_bbox() == (0, 0, 10, 10)


def test_edge_extraction_uses_active_shared_thresholds():
    detector = TemplateMatchingDetector()
    image = np.zeros((12, 12, 3), dtype=np.uint8)
    gray = np.zeros((12, 12), dtype=np.uint8)
    expected = np.ones((12, 12), dtype=np.uint8)

    with (
        patch(
            "classes.detectors.base_detector.Parameters.PF_CANNY_THRESHOLD1",
            20,
        ),
        patch(
            "classes.detectors.base_detector.Parameters.PF_CANNY_THRESHOLD2",
            80,
        ),
        patch(
            "classes.detectors.base_detector.cv2.cvtColor",
            return_value=gray,
        ),
        patch(
            "classes.detectors.base_detector.cv2.Canny",
            return_value=expected,
        ) as canny,
    ):
        result = detector.extract_edge(image)

    canny.assert_called_once_with(gray, 20, 80)
    assert result is expected


def test_initialize_target_replaces_previous_template_and_identity_features():
    """A manual retarget must never retain the previous target template."""
    detector = TemplateMatchingDetector()
    first_frame = np.zeros((24, 24, 3), dtype=np.uint8)
    first_frame[4:16, 4:16] = (0, 0, 255)
    second_frame = np.zeros((24, 24, 3), dtype=np.uint8)
    second_frame[6:18, 6:18] = (0, 255, 0)

    detector.initialize_target(first_frame, (4, 4, 12, 12))
    first_template = detector.template.copy()
    first_features = detector.initial_features.copy()

    detector.initialize_target(second_frame, (6, 6, 12, 12))

    assert np.array_equal(detector.template, second_frame[6:18, 6:18])
    assert np.array_equal(detector.initial_template, detector.template)
    assert not np.array_equal(detector.template, first_template)
    assert not np.array_equal(detector.initial_features, first_features)
    assert np.array_equal(detector.initial_features, detector.adaptive_features)
    assert detector.get_latest_bbox() == (6, 6, 12, 12)


def test_initialize_target_rejects_out_of_frame_roi():
    detector = TemplateMatchingDetector()
    frame = np.zeros((24, 24, 3), dtype=np.uint8)

    with pytest.raises(ValueError, match="inside the frame"):
        detector.initialize_target(frame, (20, 20, 8, 8))


def test_invalid_recovery_roi_is_rejected_before_template_matching():
    detector = TemplateMatchingDetector()
    frame = np.zeros((60, 80, 3), dtype=np.uint8)
    detector.initialize_target(frame, (10, 10, 20, 12))

    with patch(
        "classes.detectors.template_matching_detector.cv2.matchTemplate"
    ) as match_template:
        result = detector.smart_redetection(
            frame,
            roi=(1000, 1000, 20, 20),
        )

    assert result is False
    match_template.assert_not_called()


def test_trusted_recovery_view_updates_without_replacing_initial_identity():
    detector = TemplateMatchingDetector()
    initial_frame = np.zeros((40, 40, 3), dtype=np.uint8)
    initial_frame[10:22, 10:30] = (0, 0, 255)
    changed_frame = np.zeros((40, 40, 3), dtype=np.uint8)
    changed_frame[10:22, 10:30] = (0, 255, 0)
    detector.initialize_target(initial_frame, (10, 10, 20, 12))
    initial_template = detector.initial_template.copy()

    detector.update_template(changed_frame, (10, 10, 20, 12))

    assert np.array_equal(detector.initial_template, initial_template)
    assert np.array_equal(detector.template, initial_template)
    assert np.array_equal(
        detector.trusted_template,
        changed_frame[10:22, 10:30],
    )
    expected_features = BaseDetector.extract_features(
        detector,
        changed_frame,
        (10, 10, 20, 12),
    )
    assert np.array_equal(detector.trusted_features, expected_features)

    with patch(
        "classes.detectors.template_matching_detector.Parameters.APPEARANCE_CONFIDENCE_THRESHOLD",
        0.99,
    ):
        assert detector.validate_match(changed_frame, (10, 10, 20, 12)) is True


def test_trusted_view_refresh_skips_out_of_frame_tracker_geometry():
    detector = TemplateMatchingDetector()
    frame = np.zeros((24, 24, 3), dtype=np.uint8)
    detector.initialize_target(frame, (4, 4, 10, 10))
    trusted_before = detector.trusted_template.copy()

    detector.update_template(frame, (20, 20, 10, 10))

    assert np.array_equal(detector.trusted_template, trusted_before)


def test_multiscale_recovery_can_select_trusted_recent_view():
    detector = TemplateMatchingDetector()
    detector.template = np.zeros((4, 4, 3), dtype=np.uint8)
    detector.initial_template = detector.template.copy()
    detector.trusted_template = np.ones((4, 4, 3), dtype=np.uint8)
    detector.method = cv2.TM_CCOEFF_NORMED
    frame = np.zeros((12, 12, 3), dtype=np.uint8)

    with (
        patch(
            "classes.detectors.template_matching_detector.Parameters.TEMPLATE_MATCHING_SCALES",
            [1.0],
        ),
        patch(
            "classes.detectors.template_matching_detector.Parameters.TEMPLATE_MATCHING_THRESHOLD",
            0.7,
        ),
        patch(
            "classes.detectors.template_matching_detector.cv2.matchTemplate",
            side_effect=[
                np.array([[0.75]], dtype=np.float32),
                np.array([[0.90]], dtype=np.float32),
            ],
        ),
    ):
        matched, bbox = detector.perform_multiscale_template_matching(frame)

    assert matched is True
    assert bbox == (0, 0, 4, 4)
    assert detector.latest_template_source == "trusted"


def test_detector_identity_snapshot_survives_reinitialization_side_effects():
    detector = TemplateMatchingDetector()
    first_frame = np.zeros((32, 32, 3), dtype=np.uint8)
    first_frame[4:16, 4:16] = (10, 20, 30)
    replacement_frame = np.zeros((32, 32, 3), dtype=np.uint8)
    replacement_frame[8:20, 8:20] = (200, 100, 50)
    detector.initialize_target(first_frame, (4, 4, 12, 12))
    identity = detector.snapshot_identity_state()

    detector.initialize_target(replacement_frame, (8, 8, 12, 12))
    detector.restore_identity_state(identity)

    assert np.array_equal(
        detector.initial_template,
        first_frame[4:16, 4:16],
    )
    assert np.array_equal(detector.template, detector.initial_template)


def test_multiscale_template_matching_rejects_score_below_configured_threshold():
    """The candidate search must not turn every finite best score into a match."""
    detector = TemplateMatchingDetector()
    detector.template = np.ones((4, 4, 3), dtype=np.uint8)
    detector.method = cv2.TM_CCOEFF_NORMED
    frame = np.zeros((12, 12, 3), dtype=np.uint8)

    with (
        patch(
            "classes.detectors.template_matching_detector.Parameters.TEMPLATE_MATCHING_SCALES",
            [1.0],
        ),
        patch(
            "classes.detectors.template_matching_detector.Parameters.TEMPLATE_MATCHING_THRESHOLD",
            0.7,
        ),
        patch(
            "classes.detectors.template_matching_detector.cv2.matchTemplate",
            return_value=np.array([[0.69]], dtype=np.float32),
        ),
    ):
        matched, bbox = detector.perform_multiscale_template_matching(frame)

    assert matched is False
    assert bbox == (0, 0, 0, 0)
    assert detector.latest_match_score == pytest.approx(0.69)


def test_multiscale_template_matching_accepts_score_at_configured_threshold():
    detector = TemplateMatchingDetector()
    detector.template = np.ones((4, 4, 3), dtype=np.uint8)
    detector.method = cv2.TM_CCOEFF_NORMED
    frame = np.zeros((12, 12, 3), dtype=np.uint8)

    with (
        patch(
            "classes.detectors.template_matching_detector.Parameters.TEMPLATE_MATCHING_SCALES",
            [1.0],
        ),
        patch(
            "classes.detectors.template_matching_detector.Parameters.TEMPLATE_MATCHING_THRESHOLD",
            0.7,
        ),
        patch(
            "classes.detectors.template_matching_detector.cv2.matchTemplate",
            return_value=np.array([[0.70]], dtype=np.float32),
        ),
    ):
        matched, bbox = detector.perform_multiscale_template_matching(frame)

    assert matched is True
    assert bbox == (0, 0, 4, 4)


def test_recovery_rejects_lookalike_ambiguity_without_replacing_identity():
    rng = np.random.default_rng(22)
    target = rng.integers(0, 256, size=(12, 16, 3), dtype=np.uint8)
    initial_frame = np.zeros((80, 120, 3), dtype=np.uint8)
    initial_frame[10:22, 10:26] = target
    ambiguous_frame = np.zeros_like(initial_frame)
    ambiguous_frame[20:32, 15:31] = target
    ambiguous_frame[45:57, 80:96] = target
    unique_frame = np.zeros_like(initial_frame)
    unique_frame[45:57, 80:96] = target

    detector = TemplateMatchingDetector()
    detector.initialize_target(initial_frame, (10, 10, 16, 12))
    initial_identity = detector.initial_template.copy()

    with (
        patch(
            "classes.detectors.template_matching_detector.Parameters.TEMPLATE_MATCHING_SCALES",
            [1.0],
        ),
        patch(
            "classes.detectors.template_matching_detector.Parameters.TEMPLATE_MATCHING_THRESHOLD",
            0.99,
        ),
        patch(
            "classes.detectors.template_matching_detector.Parameters.APPEARANCE_CONFIDENCE_THRESHOLD",
            0.99,
        ),
        patch(
            "classes.detectors.template_matching_detector.Parameters.REDETECTION_MIN_CONFIDENCE_MARGIN",
            0.05,
            create=True,
        ),
    ):
        ambiguous = detector.propose_recovery(ambiguous_frame)
        recovered = detector.propose_recovery(unique_frame)

    assert ambiguous.accepted is False
    assert ambiguous.ambiguous is True
    assert ambiguous.reason == "ambiguous_candidates"
    assert ambiguous.candidate_count == 2
    assert recovered.accepted is True
    assert recovered.candidate.bbox == (80, 45, 16, 12)
    assert np.array_equal(detector.initial_template, initial_identity)


def test_recovery_candidate_nms_merges_duplicate_template_scale_proposals():
    detector = TemplateMatchingDetector()
    detector.template = np.ones((4, 4, 3), dtype=np.uint8)
    detector.initial_template = detector.template.copy()
    detector.method = cv2.TM_CCOEFF_NORMED
    frame = np.zeros((12, 12, 3), dtype=np.uint8)
    response = np.zeros((9, 9), dtype=np.float32)
    response[2, 3] = 0.95
    response[3, 4] = 0.94

    with (
        patch(
            "classes.detectors.template_matching_detector.Parameters.TEMPLATE_MATCHING_SCALES",
            [1.0],
        ),
        patch(
            "classes.detectors.template_matching_detector.Parameters.TEMPLATE_MATCHING_THRESHOLD",
            0.7,
        ),
        patch(
            "classes.detectors.template_matching_detector.Parameters.REDETECTION_CANDIDATE_NMS_IOU",
            0.3,
            create=True,
        ),
        patch(
            "classes.detectors.template_matching_detector.cv2.matchTemplate",
            return_value=response,
        ),
    ):
        candidates = detector._find_template_match_candidates(frame)

    assert len(candidates) == 1
    assert candidates[0].bbox == (3, 2, 4, 4)


def test_detector_factory_creates_supported_detector():
    """Factory should create supported detectors by stable algorithm name."""
    detector = create_detector("TemplateMatching")

    assert isinstance(detector, TemplateMatchingDetector)


def test_template_confidence_clamps_cosine_roundoff():
    """Numerical cosine roundoff must remain within the confidence contract."""
    detector = TemplateMatchingDetector()
    features = np.ones((2, 2), dtype=np.float32)

    with (
        patch(
            "classes.detectors.template_matching_detector.np.dot",
            return_value=1.000000119,
        ),
        patch(
            "classes.detectors.template_matching_detector.np.linalg.norm",
            side_effect=[1.0, 1.0],
        ),
    ):
        confidence = detector.compute_appearance_confidence(features, features)

    assert confidence == 1.0


def test_template_confidence_rejects_materially_invalid_high_score():
    """A broken similarity source must fail closed instead of gaining confidence."""
    detector = TemplateMatchingDetector()
    features = np.ones((2, 2), dtype=np.float32)

    with (
        patch(
            "classes.detectors.template_matching_detector.np.dot",
            return_value=1.01,
        ),
        patch(
            "classes.detectors.template_matching_detector.np.linalg.norm",
            side_effect=[1.0, 1.0],
        ),
    ):
        confidence = detector.compute_appearance_confidence(features, features)

    assert confidence == 0.0


def test_detector_factory_rejects_unknown_detector():
    """Factory should return None for unsupported detector names."""
    assert create_detector("unknown-detector") is None
