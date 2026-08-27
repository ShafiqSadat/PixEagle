"""Tests for the model-backed OpenCV VitTrack adapter."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from classes.tracker_artifacts import ResolvedTrackerArtifact, TrackerArtifactError
from classes.trackers.vittrack_tracker import VitTrackTracker
from tests.fixtures.mock_opencv import MockVideoHandler


class FakeVitRuntime:
    def __init__(self, *, score: float = 0.8):
        self.score = score
        self.initialized = False

    def init(self, _frame, _bbox):
        self.initialized = True

    def update(self, _frame):
        return True, (102, 101, 48, 31)

    def getTrackingScore(self):
        return self.score


def _artifact() -> ResolvedTrackerArtifact:
    return ResolvedTrackerArtifact(
        artifact_id="opencv_vittrack_2023sep",
        path=Path("/tmp/verified-vittrack.onnx"),
        sha256="a" * 64,
        size_bytes=714726,
        publisher="OpenCV Zoo",
        source_url="https://example.invalid/source",
        license="Apache-2.0",
    )


def _opencv_mock(runtime: FakeVitRuntime):
    module = MagicMock()
    params = MagicMock()
    module.TrackerVit_Params.return_value = params
    module.TrackerVit_create.return_value = runtime
    module.__version__ = "4.13.0.mock"
    module.error = RuntimeError
    return module, params


@pytest.mark.unit
def test_vittrack_uses_verified_artifact_and_configured_runtime_params():
    runtime = FakeVitRuntime()
    cv2_mock, params = _opencv_mock(runtime)
    config = {
        "backend_id": 3,
        "target_id": 7,
        "native_score_threshold": 0.31,
        "model_score_weight": 0.72,
    }
    with (
        patch("classes.trackers.vittrack_tracker.cv2", cv2_mock),
        patch("classes.trackers.vittrack_tracker.resolve_tracker_artifact", return_value=_artifact()),
        patch("classes.trackers.csrt_tracker.Parameters") as parameters,
    ):
        parameters.VitTrack_Tracker = config
        parameters.ClassicTracker_Common = {}
        parameters.CENTER_HISTORY_LENGTH = 20
        parameters.ESTIMATOR_HISTORY_LENGTH = 20
        parameters.USE_ESTIMATOR = False
        tracker = VitTrackTracker(MockVideoHandler(640, 480))

    assert params.net == "/tmp/verified-vittrack.onnx"
    assert params.backend == 3
    assert params.target == 7
    assert params.tracking_score_threshold == pytest.approx(0.31)
    assert tracker.model_score_weight == pytest.approx(0.72)
    assert tracker.tracker_name == "VitTrack"


@pytest.mark.unit
def test_vittrack_missing_artifact_has_one_actionable_error():
    runtime = FakeVitRuntime()
    cv2_mock, _params = _opencv_mock(runtime)
    with (
        patch("classes.trackers.vittrack_tracker.cv2", cv2_mock),
        patch(
            "classes.trackers.vittrack_tracker.resolve_tracker_artifact",
            side_effect=TrackerArtifactError("missing"),
        ),
    ):
        with pytest.raises(RuntimeError, match="make install-tracker-artifacts"):
            VitTrackTracker(MockVideoHandler(640, 480))


@pytest.mark.unit
def test_vittrack_combines_native_score_and_shared_validation_confidence():
    runtime = FakeVitRuntime(score=0.8)
    cv2_mock, _params = _opencv_mock(runtime)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    with (
        patch("classes.trackers.vittrack_tracker.cv2", cv2_mock),
        patch("classes.trackers.vittrack_tracker.resolve_tracker_artifact", return_value=_artifact()),
        patch("classes.trackers.csrt_tracker.Parameters") as parameters,
    ):
        parameters.VitTrack_Tracker = {
            "performance_mode": "balanced",
            "model_score_weight": 0.75,
            "confidence_threshold": 0.0,
            "enable_multiframe_validation": False,
        }
        parameters.ClassicTracker_Common = {}
        parameters.CENTER_HISTORY_LENGTH = 20
        parameters.ESTIMATOR_HISTORY_LENGTH = 20
        parameters.USE_ESTIMATOR = False
        parameters.MOTION_CONFIDENCE_WEIGHT = 0.5
        parameters.APPEARANCE_CONFIDENCE_WEIGHT = 0.5
        tracker = VitTrackTracker(MockVideoHandler(640, 480))
        tracker.start_tracking(frame, (100, 100, 50, 30))
        success, _bbox = tracker.update(frame)

    assert success is True
    assert tracker.native_tracking_score == pytest.approx(0.8)
    assert 0.0 <= tracker.confidence <= 1.0
    output = tracker.get_output()
    assert output.metadata["tracker_algorithm"] == "VitTrack"
    assert output.metadata["artifact_sha256"] == "a" * 64
    assert output.quality_metrics["native_tracking_score"] == pytest.approx(0.8)


@pytest.mark.unit
def test_vittrack_is_registered_as_a_classic_tracker():
    from classes.trackers.tracker_factory import TRACKER_REGISTRY

    assert TRACKER_REGISTRY["VitTrack"] is VitTrackTracker
