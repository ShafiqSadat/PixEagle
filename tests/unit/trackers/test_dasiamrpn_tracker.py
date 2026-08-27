"""Tests for the optional OpenCV DaSiamRPN adapter."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from classes.tracker_artifacts import ResolvedTrackerArtifact, TrackerArtifactError
from classes.trackers.dasiamrpn_tracker import DaSiamRPNTracker
from tests.fixtures.mock_opencv import MockVideoHandler


class FakeDaSiamRuntime:
    def __init__(self, *, score: float = 0.9):
        self.score = score

    def init(self, _frame, _bbox):
        return None

    def update(self, _frame):
        return True, (102, 101, 48, 31)

    def getTrackingScore(self):
        return self.score


def _artifact(artifact_id: str) -> ResolvedTrackerArtifact:
    return ResolvedTrackerArtifact(
        artifact_id=artifact_id,
        path=Path(f"/tmp/{artifact_id}.onnx"),
        sha256=artifact_id[-1] * 64,
        size_bytes=1024,
        publisher="OpenCV sample / DaSiamRPN authors",
        source_url="https://example.invalid/source",
        license="MIT",
    )


def _resolve_artifact(_config, **kwargs):
    artifact_id = kwargs["default_artifact_id"]
    return _artifact(artifact_id)


def _opencv_mock(runtime: FakeDaSiamRuntime):
    module = MagicMock()
    params = MagicMock()
    module.TrackerDaSiamRPN_Params.return_value = params
    module.TrackerDaSiamRPN_create.return_value = runtime
    return module, params


def _parameters(parameters, config):
    parameters.DaSiamRPN_Tracker = config
    parameters.ClassicTracker_Common = {}
    parameters.CENTER_HISTORY_LENGTH = 20
    parameters.ESTIMATOR_HISTORY_LENGTH = 20
    parameters.USE_ESTIMATOR = False
    parameters.MOTION_CONFIDENCE_WEIGHT = 0.5
    parameters.APPEARANCE_CONFIDENCE_WEIGHT = 0.5
    parameters.APPEARANCE_CONFIDENCE_THRESHOLD = 0.7


@pytest.mark.unit
def test_dasiamrpn_uses_three_verified_artifacts_and_runtime_params():
    runtime = FakeDaSiamRuntime()
    cv2_mock, params = _opencv_mock(runtime)
    config = {"backend_id": 3, "target_id": 7, "model_score_weight": 0.8}
    with (
        patch("classes.trackers.dasiamrpn_tracker.cv2", cv2_mock),
        patch(
            "classes.trackers.dasiamrpn_tracker.resolve_tracker_artifact",
            side_effect=_resolve_artifact,
        ),
        patch("classes.trackers.csrt_tracker.Parameters") as parameters,
    ):
        _parameters(parameters, config)
        tracker = DaSiamRPNTracker(MockVideoHandler(640, 480))

    assert params.model.endswith("opencv_dasiamrpn_model.onnx")
    assert params.kernel_r1.endswith("opencv_dasiamrpn_kernel_r1.onnx")
    assert params.kernel_cls1.endswith("opencv_dasiamrpn_kernel_cls1.onnx")
    assert params.backend == 3
    assert params.target == 7
    assert tracker.tracker_name == "DaSiamRPN"


@pytest.mark.unit
def test_dasiamrpn_missing_artifact_has_one_actionable_error():
    cv2_mock, _params = _opencv_mock(FakeDaSiamRuntime())
    with (
        patch("classes.trackers.dasiamrpn_tracker.cv2", cv2_mock),
        patch(
            "classes.trackers.dasiamrpn_tracker.resolve_tracker_artifact",
            side_effect=TrackerArtifactError("missing"),
        ),
    ):
        with pytest.raises(RuntimeError, match="make install-dasiamrpn-artifacts"):
            DaSiamRPNTracker(MockVideoHandler(640, 480))


@pytest.mark.unit
def test_dasiamrpn_native_score_is_gated_and_reported():
    runtime = FakeDaSiamRuntime(score=0.9)
    cv2_mock, _params = _opencv_mock(runtime)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    config = {
        "performance_mode": "balanced",
        "native_score_threshold": 0.2,
        "model_score_weight": 0.8,
        "confidence_threshold": 0.0,
        "enable_multiframe_validation": False,
    }
    with (
        patch("classes.trackers.dasiamrpn_tracker.cv2", cv2_mock),
        patch(
            "classes.trackers.dasiamrpn_tracker.resolve_tracker_artifact",
            side_effect=_resolve_artifact,
        ),
        patch("classes.trackers.csrt_tracker.Parameters") as parameters,
    ):
        _parameters(parameters, config)
        tracker = DaSiamRPNTracker(MockVideoHandler(640, 480))
        tracker.start_tracking(frame, (100, 100, 50, 30))
        success, _bbox = tracker.update(frame)

    assert success is True
    output = tracker.get_output()
    assert output.metadata["tracker_algorithm"] == "DaSiamRPN"
    assert output.quality_metrics["native_tracking_score"] == pytest.approx(0.9)
    assert set(output.metadata["artifacts"]) == {"model", "kernel_r1", "kernel_cls1"}

    runtime.score = 0.1
    success, _bbox = tracker.update(frame)
    assert success is False
    assert tracker.last_failure_info.loss_reason == "low_confidence"


@pytest.mark.unit
def test_dasiamrpn_is_registered_as_a_classic_tracker():
    from classes.trackers.tracker_factory import TRACKER_REGISTRY

    assert TRACKER_REGISTRY["DaSiamRPN"] is DaSiamRPNTracker


@pytest.mark.unit
def test_dasiamrpn_uses_release_defaults_when_local_config_predates_tracker():
    tracker = object.__new__(DaSiamRPNTracker)
    with patch(
        "classes.trackers.model_backed_tracker.csrt_tracker.Parameters",
        SimpleNamespace(),
    ):
        config = tracker._tracker_config()

    assert config["model_artifact_id"] == "opencv_dasiamrpn_model"
    assert config["native_score_threshold"] == pytest.approx(0.20)
