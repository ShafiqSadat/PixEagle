"""Deterministic tests for the commit-gated Sparse Flow core."""

from pathlib import Path

import numpy as np
import pytest
import yaml

from classes.trackers.sparse_flow_core import SparseFlowConfig, SparseFlowCore


PROJECT_ROOT = Path(__file__).resolve().parents[3]
INITIAL_BBOX = (100, 80, 80, 60)


def _config(**overrides):
    defaults = yaml.safe_load(
        (PROJECT_ROOT / "configs/config_default.yaml").read_text(encoding="utf-8")
    )["SparseFlow_Tracker"]
    defaults.update(overrides)
    return SparseFlowConfig.from_mapping(defaults)


def _scene(dx: int = 0, dy: int = 0, *, visible: bool = True) -> np.ndarray:
    frame = np.zeros((240, 320), dtype=np.uint8)
    if visible:
        texture = np.random.default_rng(8241).integers(
            0,
            256,
            (INITIAL_BBOX[3], INITIAL_BBOX[2]),
            dtype=np.uint8,
        )
        x, y, width, height = INITIAL_BBOX
        frame[y + dy : y + dy + height, x + dx : x + dx + width] = texture
    return frame


def test_config_rejects_missing_and_inconsistent_parameters():
    with pytest.raises(ValueError, match="feature_strategy"):
        SparseFlowConfig.from_mapping({})

    with pytest.raises(ValueError, match="min_points"):
        _config(max_points=6, min_points=7)

    with pytest.raises(ValueError, match="odd integer"):
        _config(lk_window_size=20)


def test_translation_proposal_advances_only_after_commit():
    core = SparseFlowCore(_config())
    assert core.initialize(_scene(), INITIAL_BBOX) == INITIAL_BBOX

    proposal = core.propose(_scene(dx=7, dy=4))

    assert proposal.success is True
    assert proposal.reason == "measurement"
    assert proposal.bbox == pytest.approx((107, 84, 80, 60), abs=1)
    assert proposal.metrics.confidence >= 0.9
    assert proposal.metrics.retained_point_count >= core.config.min_points
    assert core.bbox == INITIAL_BBOX

    core.commit(proposal, proposal.metrics.confidence)
    assert core.bbox == proposal.bbox


def test_occlusion_fails_without_corrupting_last_accepted_state():
    core = SparseFlowCore(_config())
    core.initialize(_scene(), INITIAL_BBOX)

    failed = core.propose(_scene(visible=False))

    assert failed.success is False
    assert failed.reason in {
        "insufficient_consistent_points",
        "insufficient_geometry_consensus",
        "appearance_mismatch",
    }
    assert core.bbox == INITIAL_BBOX

    recovered_measurement = core.propose(_scene(dx=5, dy=3))
    assert recovered_measurement.success is True
    assert recovered_measurement.bbox == pytest.approx((105, 83, 80, 60), abs=1)


def test_stale_proposal_cannot_overwrite_newer_accepted_state():
    core = SparseFlowCore(_config())
    core.initialize(_scene(), INITIAL_BBOX)
    first = core.propose(_scene(dx=3, dy=2))
    competing = core.propose(_scene(dx=4, dy=2))
    assert first.success and competing.success

    core.commit(first, first.metrics.confidence)

    with pytest.raises(RuntimeError, match="no longer matches"):
        core.commit(competing, competing.metrics.confidence)


def test_commit_rejects_invalid_confidence_without_advancing_state():
    core = SparseFlowCore(_config())
    core.initialize(_scene(), INITIAL_BBOX)
    proposal = core.propose(_scene(dx=3, dy=2))
    assert proposal.success

    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        core.commit(proposal, float("nan"))

    assert core.bbox == INITIAL_BBOX


def test_uniform_target_is_rejected_at_initialization():
    core = SparseFlowCore(_config(feature_strategy="gftt"))

    with pytest.raises(ValueError, match="enough trackable points"):
        core.initialize(np.zeros((240, 320), dtype=np.uint8), INITIAL_BBOX)
