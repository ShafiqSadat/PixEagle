"""Sparse Flow integration tests against the shared tracker contract."""

from pathlib import Path

import numpy as np
import pytest
import yaml

from classes.parameters import Parameters
from classes.trackers.sparse_flow_tracker import SparseFlowTracker
from tests.fixtures.mock_opencv import MockAppController, MockVideoHandler


PROJECT_ROOT = Path(__file__).resolve().parents[3]
INITIAL_BBOX = (100, 80, 80, 60)


def _config():
    return yaml.safe_load(
        (PROJECT_ROOT / "configs/config_default.yaml").read_text(encoding="utf-8")
    )["SparseFlow_Tracker"]


def _scene(dx: int = 0, dy: int = 0, *, visible: bool = True) -> np.ndarray:
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    if visible:
        texture = np.random.default_rng(8241).integers(
            0,
            256,
            (INITIAL_BBOX[3], INITIAL_BBOX[2], 3),
            dtype=np.uint8,
        )
        x, y, width, height = INITIAL_BBOX
        frame[y + dy : y + dy + height, x + dx : x + dx + width] = texture
    return frame


@pytest.fixture
def tracker(monkeypatch):
    monkeypatch.setattr(Parameters, "SparseFlow_Tracker", _config(), raising=False)
    return SparseFlowTracker(
        MockVideoHandler(width=320, height=240),
        detector=None,
        app_controller=MockAppController(),
    )


def test_measurement_is_published_through_standard_output(tracker):
    tracker.start_tracking(_scene(), INITIAL_BBOX)

    success, bbox = tracker.update(_scene(dx=6, dy=3))
    output = tracker.get_output()

    assert success is True
    assert bbox == pytest.approx((106, 83, 80, 60), abs=1)
    assert output.tracking_active is True
    assert output.metadata["tracker_algorithm"] == "SparseFlow"
    assert output.raw_data["measurement_source"] == "measurement"
    assert output.raw_data["usable_for_following"] is True
    assert output.raw_data["retained_point_count"] >= tracker.config.min_points


def test_failed_measurement_is_diagnostic_and_not_follower_eligible(tracker):
    tracker.start_tracking(_scene(), INITIAL_BBOX)

    success, bbox = tracker.update(_scene(visible=False))
    output = tracker.get_output()

    assert success is False
    assert bbox == INITIAL_BBOX
    assert tracker.flow_core.bbox == INITIAL_BBOX
    assert output.raw_data["prediction_only"] is True
    assert output.raw_data["data_is_stale"] is True
    assert output.raw_data["usable_for_following"] is False
    assert output.metadata["prediction_command_eligible"] is False


def test_stop_clears_tracker_and_flow_state(tracker):
    tracker.start_tracking(_scene(), INITIAL_BBOX)

    tracker.stop_tracking()

    assert tracker.tracking_started is False
    assert tracker.bbox is None
    assert tracker.flow_core.initialized is False
    assert tracker.last_flow_reason == "inactive"


def test_factory_creates_sparse_flow_tracker(monkeypatch):
    from classes.trackers.tracker_factory import create_tracker

    monkeypatch.setattr(Parameters, "SparseFlow_Tracker", _config(), raising=False)
    created = create_tracker(
        "SparseFlow",
        MockVideoHandler(width=320, height=240),
        detector=None,
        app_controller=MockAppController(),
    )

    assert isinstance(created, SparseFlowTracker)
