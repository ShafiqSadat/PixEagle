"""Shared classic-tracker recovery search contract tests."""

import pytest

from classes.tracking_recovery import (
    RecoveryHint,
    RecoverySearchRequirements,
    build_recovery_search_plan,
)


pytestmark = [pytest.mark.unit, pytest.mark.trackers]


def _plan(attempt, *, hint=None, max_attempts=5, requirements=None):
    return build_recovery_search_plan(
        frame_shape=(600, 800, 3),
        hint=hint or RecoveryHint(
            predicted_center=(400.0, 300.0),
            last_seen_bbox=(350, 275, 100, 50),
            prediction_reliable=True,
        ),
        requirements=requirements or RecoverySearchRequirements(100, 50),
        attempt=attempt,
        max_attempts=max_attempts,
        min_local_radius=50,
        max_local_radius=300,
        uncertainty_scale_factor=2.0,
        global_search_attempts=2,
    )


def test_local_recovery_search_expands_monotonically_before_global_fallback():
    plans = [_plan(attempt) for attempt in range(1, 6)]

    assert [plan.scope for plan in plans] == [
        "local",
        "local",
        "local",
        "global",
        "global",
    ]
    assert [plan.radius for plan in plans[:3]] == [200, 250, 300]
    assert [plan.roi[2] for plan in plans[:3]] == [400, 500, 600]
    assert plans[3].roi is None
    assert plans[4].roi is None


def test_out_of_frame_prediction_is_clamped_to_a_valid_search_region():
    plan = _plan(
        1,
        hint=RecoveryHint(
            predicted_center=(1400.0, -200.0),
            last_seen_bbox=(740, 10, 100, 50),
            prediction_reliable=True,
        ),
    )

    assert plan.scope == "local"
    assert plan.anchor_source == "prediction"
    x, y, width, height = plan.roi
    assert (x, y, width, height) == (400, 0, 400, 400)
    assert x >= 0 and y >= 0
    assert x + width <= 800
    assert y + height <= 600


def test_unreliable_prediction_falls_back_to_last_confirmed_measurement():
    plan = _plan(
        1,
        hint=RecoveryHint(
            predicted_center=(790.0, 590.0),
            last_seen_bbox=(40, 60, 100, 50),
            prediction_reliable=False,
        ),
    )

    assert plan.anchor_source == "last_measurement"
    assert plan.roi == (0, 0, 400, 400)


def test_detector_minimum_dimensions_are_never_violated():
    plan = _plan(
        1,
        requirements=RecoverySearchRequirements(500, 450),
    )

    assert plan.roi is None or (
        plan.roi[2] >= 500 and plan.roi[3] >= 450
    )


def test_missing_local_hint_uses_full_frame_without_invalid_geometry():
    plan = _plan(
        1,
        hint=RecoveryHint(),
    )

    assert plan.scope == "global"
    assert plan.anchor_source == "no_local_hint"
    assert plan.roi is None


def test_single_recovery_attempt_prioritizes_full_frame_reacquisition():
    plan = _plan(1, max_attempts=1)

    assert plan.scope == "global"
    assert plan.roi is None


def test_attempt_outside_retry_budget_is_rejected():
    with pytest.raises(ValueError, match="inside the retry budget"):
        _plan(6)
