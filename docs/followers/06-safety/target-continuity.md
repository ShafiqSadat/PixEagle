# Target Continuity

`TargetContinuitySupervisor` is the single command-authority owner between
target evidence and `OffboardCommander`:

~~~text
TrackerOutput -> TargetEvidenceSnapshot -> follower nominal CommandIntent
              -> TargetContinuitySupervisor -> OffboardCommander -> PX4
~~~

Trackers may keep predictions and last-known geometry for display and
reacquisition. Those estimates do not independently authorize vehicle commands.
Followers calculate nominal commands only from confirmed evidence; they do not
implement their own loss timers, hover/orbit actions, or inactive-output paths.
They also do not reclassify confidence or image-plane velocity. Tracker evidence
qualification is the single authority for those measurements; followers retain
only finite/profile-specific coordinate and command validation.

## Authority States

| State | Meaning |
|---|---|
| `INACTIVE` | No follow-session authority has been established |
| `ACTIVE` | Confirmed identity and fresh evidence authorize the nominal intent |
| `COASTING` | A qualified bounded-decay intent is authorized |
| `REACQUIRING` | Identity is confirmed again while authority is restored |
| `HANDOFF_PENDING` | Command authority is surrendered and PX4 handoff confirmation is pending |

Identity ambiguity, operator abort, stale vehicle state, unhealthy publication,
an unconfirmed Offboard state, or exhausted loss budgets request an immediate
handoff. Brief recover/loss flapping cannot reset the original episode budget.

## Default And Qualification Boundary

The default is `immediate_handoff`. It stops PixEagle command publication
and requests the configured terminal action, currently `hold`.

`bounded_decay` is implemented only for multicopter
`velocity_body_offboard` command preview. It decays the last confirmed
horizontal intent under independent elapsed-time and integrated-distance
budgets, then requires stable identity confirmation before restoring authority.
It is not qualified for live PX4, attitude-rate, fixed-wing, or VTOL-transition
operation. Unsupported combinations fail closed to handoff.

This repository contains unit and command-preview evidence only for bounded
decay. It does not claim SITL, HIL, field, aircraft, or PX4-observed success.

## Configuration

~~~yaml
TargetContinuity:
  MODE: immediate_handoff        # immediate_handoff | bounded_decay
  MAX_COAST_TIME_S: 1.0          # preview-only hard time budget
  MAX_COAST_DISTANCE_M: 2.0      # preview-only integrated travel budget
  REACQUIRE_CONFIRMATION_S: 0.5  # continuous confirmed evidence required
  AUTHORITY_RESTORE_TIME_S: 1.0  # bounded restoration ramp
  TERMINAL_ACTION: hold
~~~

These settings apply to every current and future follower. Strategy selection is
resolved from the follower profile's `airframe_phase` and
`control_type`, not from follower names.

## Operator Evidence

`GET /api/v1/following/telemetry` exposes the process-local
`continuity` snapshot, including authority state, reason, episode budget,
and handoff result. This is PixEagle decision evidence. Confirm PX4 mode and
vehicle response through independent telemetry before making an operational
claim.

Use command preview first:

~~~bash
make demo
~~~

The circuit breaker remains a separate final PX4 dispatch inhibit. It does not
grant continuity authority or qualify a strategy.

## Extension Rules

New followers must declare `airframe_phase` and `control_type` in
`configs/follower_commands.yaml`. A new continuity strategy belongs in
the shared capability registry and requires state-machine, controller-boundary,
schema, command-preview, and appropriate SITL/HIL evidence. Do not add
follower-name checks or follower-local loss handlers.
