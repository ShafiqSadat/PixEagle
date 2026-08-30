import time

import pytest

from classes.command_intent import CommandIntent
from classes.target_continuity import (
    AirframePhase,
    ContinuityAuthorityState,
    ContinuityContext,
    ContinuityMode,
    ContinuityPolicy,
    IdentityVerdict,
    TargetContinuitySupervisor,
    TargetEvidenceSnapshot,
    TargetEvidenceState,
)
from classes.tracker_output import TrackerDataType, TrackerOutput


def _policy(mode="immediate_handoff", **overrides):
    values = {
        "MODE": mode,
        "MAX_COAST_TIME_S": 2.0,
        "MAX_COAST_DISTANCE_M": 10.0,
        "REACQUIRE_CONFIRMATION_S": 0.5,
        "AUTHORITY_RESTORE_TIME_S": 1.0,
        "TERMINAL_ACTION": "hold",
    }
    values.update(overrides)
    return ContinuityPolicy.from_mapping(values)


def _context(
    *,
    execution_mode="COMMAND_PREVIEW",
    airframe=AirframePhase.MULTICOPTER,
    control_type="velocity_body_offboard",
    yaw=0.0,
    fresh=True,
    offboard=True,
    publisher=True,
    abort=False,
):
    return ContinuityContext(
        execution_mode=execution_mode,
        airframe_phase=airframe,
        control_type=control_type,
        vehicle_state_fresh=fresh,
        offboard_active=offboard,
        publisher_healthy=publisher,
        vehicle_yaw_deg=yaw,
        operator_abort=abort,
    )


def _evidence(state, *, epoch=7, reason="test_evidence"):
    return TargetEvidenceSnapshot(
        state=state,
        observed_at_monotonic_s=0.0,
        session_epoch=epoch,
        target_id="target-1",
        identity_verdict=(
            IdentityVerdict.CONFIRMED
            if state is TargetEvidenceState.CONFIRMED
            else IdentityVerdict.UNCONFIRMED
        ),
        reason_code=reason,
    )


def _intent(*, forward=4.0, right=2.0, down=1.0, yaw=12.0):
    return CommandIntent(
        profile_name="mc_velocity_chase",
        control_type="velocity_body_offboard",
        fields={
            "vel_body_fwd": forward,
            "vel_body_right": right,
            "vel_body_down": down,
            "yawspeed_deg_s": yaw,
        },
        source="test_follower",
    )


def _supervisor(policy):
    supervisor = TargetContinuitySupervisor(policy, clock=lambda: 0.0)
    supervisor.reset_session(session_epoch=7, reason="test_start")
    return supervisor


def test_policy_rejects_unknown_and_nonfinite_values():
    with pytest.raises(ValueError, match="Unknown TargetContinuity"):
        ContinuityPolicy.from_mapping({"UNKNOWN": 1})
    with pytest.raises(ValueError, match="finite and non-negative"):
        ContinuityPolicy.from_mapping({"MAX_COAST_TIME_S": float("nan")})
    with pytest.raises(ValueError, match="requires positive"):
        ContinuityPolicy.from_mapping(
            {"MODE": "bounded_decay", "MAX_COAST_TIME_S": 0.0}
        )


def test_tracker_output_normalizes_confirmed_predicted_and_ambiguous_evidence():
    confirmed = TrackerOutput(
        data_type=TrackerDataType.POSITION_2D,
        timestamp=time.time(),
        tracking_active=True,
        position_2d=(0.1, 0.2),
        metadata={"usable_for_following": True, "identity_confirmed": True},
    )
    predicted = TrackerOutput(
        data_type=TrackerDataType.POSITION_2D,
        timestamp=time.time(),
        tracking_active=True,
        position_2d=(0.1, 0.2),
        metadata={"prediction_only": True, "usable_for_following": False},
    )
    ambiguous = TrackerOutput(
        data_type=TrackerDataType.POSITION_2D,
        timestamp=time.time(),
        tracking_active=True,
        position_2d=(0.1, 0.2),
        metadata={
            "usable_for_following": True,
            "identity_ambiguous": True,
        },
    )

    assert TargetEvidenceSnapshot.from_tracker_output(
        confirmed, session_epoch=7, now_monotonic_s=1.0
    ).state is TargetEvidenceState.CONFIRMED
    assert TargetEvidenceSnapshot.from_tracker_output(
        predicted, session_epoch=7, now_monotonic_s=1.0
    ).state is TargetEvidenceState.PREDICTED
    assert TargetEvidenceSnapshot.from_tracker_output(
        ambiguous, session_epoch=7, now_monotonic_s=1.0
    ).state is TargetEvidenceState.AMBIGUOUS


def test_confirmed_measurement_authorizes_nominal_intent():
    supervisor = _supervisor(_policy())
    intent = _intent()
    decision = supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        intent,
        now_monotonic_s=1.0,
    )
    assert decision.authority_state is ContinuityAuthorityState.ACTIVE
    assert decision.authorized_intent is intent
    assert decision.authority_fraction == 1.0


def test_immediate_handoff_is_idempotent_after_loss():
    supervisor = _supervisor(_policy())
    supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        _intent(),
        now_monotonic_s=1.0,
    )
    first = supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT, reason="tracking_lost"),
        _context(),
        now_monotonic_s=1.1,
    )
    second = supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT, reason="tracking_lost"),
        _context(),
        now_monotonic_s=1.2,
    )
    assert first.authority_state is ContinuityAuthorityState.HANDOFF_PENDING
    assert first.authorized_intent is None
    assert first.handoff_request.request_id == second.handoff_request.request_id


def test_preview_bounded_decay_removes_vertical_and_yaw_authority():
    supervisor = _supervisor(_policy("bounded_decay"))
    supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        _intent(),
        now_monotonic_s=1.0,
    )
    first = supervisor.evaluate(
        _evidence(TargetEvidenceState.PREDICTED, reason="prediction_only"),
        _context(),
        now_monotonic_s=1.1,
    )
    second = supervisor.evaluate(
        _evidence(TargetEvidenceState.PREDICTED, reason="prediction_only"),
        _context(),
        now_monotonic_s=1.5,
    )

    assert first.authority_state is ContinuityAuthorityState.COASTING
    assert first.authorized_intent.fields["vel_body_down"] == 0.0
    assert first.authorized_intent.fields["yawspeed_deg_s"] == 0.0
    assert abs(second.authorized_intent.fields["vel_body_fwd"]) < abs(
        first.authorized_intent.fields["vel_body_fwd"]
    )
    assert second.authority_fraction < first.authority_fraction
    assert second.coast_distance_m > first.coast_distance_m


def test_body_decay_preserves_inertial_direction_when_yaw_changes():
    supervisor = _supervisor(_policy("bounded_decay"))
    supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(yaw=0.0),
        _intent(forward=4.0, right=0.0),
        now_monotonic_s=1.0,
    )
    decision = supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT),
        _context(yaw=90.0),
        now_monotonic_s=1.1,
    )
    assert decision.authorized_intent.fields["vel_body_fwd"] == pytest.approx(0.0)
    assert decision.authorized_intent.fields["vel_body_right"] < 0.0


def test_bounded_decay_never_enables_unqualified_live_coasting():
    supervisor = _supervisor(_policy("bounded_decay"))
    live = _context(execution_mode="PX4")
    supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        live,
        _intent(),
        now_monotonic_s=1.0,
    )
    decision = supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT),
        live,
        now_monotonic_s=1.1,
    )
    assert decision.authority_state is ContinuityAuthorityState.HANDOFF_PENDING
    assert "not_qualified_for_px4" in decision.reason_code


def test_attitude_rate_and_fixed_wing_profiles_handoff_without_coasting():
    for context in (
        _context(control_type="attitude_rate"),
        _context(airframe=AirframePhase.FIXED_WING),
    ):
        supervisor = _supervisor(_policy("bounded_decay"))
        nominal = CommandIntent(
            profile_name="mc_attitude_rate",
            control_type=context.control_type,
            fields={
                "rollspeed_deg_s": 1.0,
                "pitchspeed_deg_s": 1.0,
                "yawspeed_deg_s": 1.0,
                "thrust": 0.5,
            }
            if context.control_type == "attitude_rate"
            else _intent().fields,
            source="test_follower",
        )
        supervisor.evaluate(
            _evidence(TargetEvidenceState.CONFIRMED),
            context,
            nominal,
            now_monotonic_s=1.0,
        )
        decision = supervisor.evaluate(
            _evidence(TargetEvidenceState.ABSENT),
            context,
            now_monotonic_s=1.1,
        )
        assert decision.authority_state is ContinuityAuthorityState.HANDOFF_PENDING


def test_repeated_loss_does_not_reset_original_episode_budget():
    supervisor = _supervisor(
        _policy(
            "bounded_decay",
            MAX_COAST_TIME_S=1.0,
            REACQUIRE_CONFIRMATION_S=0.4,
        )
    )
    supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        _intent(forward=1.0, right=0.0),
        now_monotonic_s=1.0,
    )
    first_loss = supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT),
        _context(),
        now_monotonic_s=1.1,
    )
    supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        _intent(forward=1.0, right=0.0),
        now_monotonic_s=1.2,
    )
    second_loss = supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT),
        _context(),
        now_monotonic_s=1.4,
    )
    expired = supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT),
        _context(),
        now_monotonic_s=2.11,
    )

    assert first_loss.episode_id == second_loss.episode_id
    assert expired.authority_state is ContinuityAuthorityState.HANDOFF_PENDING
    assert expired.reason_code == "maximum_coast_time_reached"


def test_reacquisition_requires_confirmation_then_ramps_authority():
    supervisor = _supervisor(_policy("bounded_decay"))
    nominal = _intent(forward=2.0, right=0.0, down=0.0, yaw=0.0)
    supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        nominal,
        now_monotonic_s=1.0,
    )
    supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT),
        _context(),
        now_monotonic_s=1.1,
    )
    guarded = supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        nominal,
        now_monotonic_s=1.2,
    )
    restoring = supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        nominal,
        now_monotonic_s=1.8,
    )
    restored = supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        nominal,
        now_monotonic_s=2.81,
    )

    assert guarded.reason_code == "reacquire_confirmation_pending"
    assert restoring.reason_code == "target_authority_restoring"
    assert 0.0 <= restoring.authority_fraction < 1.0
    assert restored.authority_state is ContinuityAuthorityState.ACTIVE
    assert restored.authorized_intent is nominal


def test_reacquisition_cannot_extend_the_original_loss_budget():
    supervisor = _supervisor(
        _policy(
            "bounded_decay",
            MAX_COAST_TIME_S=1.0,
            REACQUIRE_CONFIRMATION_S=0.8,
        )
    )
    nominal = _intent(forward=1.0, right=0.0, down=0.0, yaw=0.0)
    supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        nominal,
        now_monotonic_s=1.0,
    )
    supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT),
        _context(),
        now_monotonic_s=1.1,
    )
    supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        nominal,
        now_monotonic_s=1.2,
    )
    expired = supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        nominal,
        now_monotonic_s=2.1,
    )

    assert expired.authority_state is ContinuityAuthorityState.HANDOFF_PENDING
    assert expired.reason_code == "maximum_coast_time_reached"


def test_session_reset_clears_episode_and_handoff_history():
    supervisor = _supervisor(_policy())
    supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT),
        _context(),
        now_monotonic_s=1.0,
    )
    supervisor.record_handoff_result(success=False, detail="not observed")

    supervisor.reset_session(session_epoch=8, reason="new_target")
    status = supervisor.get_status()

    assert status["session_epoch"] == 8
    assert status["episode_id"] == 0
    assert status["handoff_pending"] is False
    assert status["last_handoff_result"] is None


def test_abort_and_ambiguous_identity_can_only_reduce_authority():
    supervisor = _supervisor(_policy("bounded_decay"))
    supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(),
        _intent(),
        now_monotonic_s=1.0,
    )
    ambiguous = supervisor.evaluate(
        _evidence(TargetEvidenceState.AMBIGUOUS),
        _context(),
        now_monotonic_s=1.1,
    )
    assert ambiguous.authority_fraction == 0.0

    supervisor.reset_session(session_epoch=7, reason="restart")
    aborted = supervisor.evaluate(
        _evidence(TargetEvidenceState.CONFIRMED),
        _context(abort=True),
        _intent(),
        now_monotonic_s=2.0,
    )
    assert aborted.authority_state is ContinuityAuthorityState.HANDOFF_PENDING
    assert aborted.reason_code == "operator_abort"


def test_handoff_result_distinguishes_local_request_from_confirmation():
    supervisor = _supervisor(_policy())
    supervisor.evaluate(
        _evidence(TargetEvidenceState.ABSENT),
        _context(),
        now_monotonic_s=1.0,
    )
    assert supervisor.get_status()["handoff_pending"] is True

    supervisor.record_handoff_result(success=False, detail="PX4 did not acknowledge")
    assert supervisor.get_status()["authority_state"] == "HANDOFF_PENDING"
    assert supervisor.get_status()["last_handoff_result"]["success"] is False

    supervisor.record_handoff_result(success=True, detail="PX4 Hold acknowledged")
    status = supervisor.get_status()
    assert status["authority_state"] == "INACTIVE"
    assert status["handoff_pending"] is False
