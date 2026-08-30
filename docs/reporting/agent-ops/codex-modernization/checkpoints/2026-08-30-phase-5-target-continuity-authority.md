# Phase 5 Checkpoint: Target-Evidence Command Authority

Date: 2026-08-30
Issue: PXE-0169
Status: implementation and VPS command-preview validation complete; PX4 acceptance pending

## Problem

Target-loss policy existed in follower implementations, follower overrides,
safety actions, inactive-output hooks, and telemetry. These paths could disagree
about whether stale, predicted, or ambiguous evidence retained command authority.
They also could report a local stop request as though PX4 had acknowledged the
handoff.

## Decision

- Normalize tracker output into one target-evidence snapshot.
- Let followers calculate nominal commands only from confirmed evidence.
- Place one `TargetContinuitySupervisor` before `OffboardCommander` submission.
- Select capabilities by physical `airframe_phase` and `control_type`, never by
  follower name.
- Preserve one time/distance budget through loss/recovery flapping; predictions
  and identity ambiguity never grant authority.
- Use immediate Hold handoff as the live default and report success only after
  the Offboard stop action is observed as executed.
- Keep bounded horizontal decay and guarded restoration command-preview-only.
  Live PX4, attitude-rate, fixed-wing, and VTOL-transition coasting fail closed
  until separate evidence qualifies them.

## Scope

The slice adds the supervisor, state/API contracts, command-profile airframe
metadata, generated config schema, dashboard status, and validation-plan
assertions. It deletes `TargetLossHandler`, follower-local loss logic, obsolete
tests, and their active config/UI/docs. Retirement metadata handles existing
operator configuration without silently preserving old authority behavior.

## Validation

- Affected controller/follower/API/config regression suite: `284 passed`
- Complete follower contract suite: `187 passed`
- Required Phase 0 API/reload gate: `73 passed`
- Follower-command/drone-interface contract subset: `172 passed`
- Full dashboard from the preceding frontend part of this slice: `59` suites,
  `405` tests passed; this follow-up changed no dashboard files
- Dashboard lint: passed
- Dashboard production build: passed
- Active documentation consistency: `31 passed`
- `bash scripts/check_schema.sh`: passed (`43` sections, `603` parameters)
- Python syntax compilation for touched runtime modules: passed
- `git diff --check`: passed
- Authenticated public browser workflow on run
  `pixeagle_manual_396dd27e-dae6-4dc7-9e53-9c00f901e672`: passed
- CSRT target selection reached `active_usable`; Circuit Breaker remained active;
  MC Velocity Chase produced 29 consecutive sampled intents while forward
  velocity ramped from `0.05` to `0.5 m/s`
- Every command-preview sample reported `commands_sent_to_px4=false`; no MAVSDK
  Server, MAVLink2REST process, or listener on TCP `50051`/`8088` was present

## Evidence Boundary

These results establish process-local logic, browser control-path, and
command-preview contracts only.
No PX4, SITL, HIL, Raspberry Pi, camera, vehicle-response, flight, or field
success is claimed. Before live acceptance, record exact PX4 mode transition,
publisher shutdown, telemetry, ULog/tlog, vehicle configuration, and operator
abort evidence. Bounded live coasting remains disabled.

## Next Test

Complete operator browser acceptance, then run the planned SITL matrix with
`TargetContinuity.MODE` first set to `immediate_handoff`, then explicitly to
`bounded_decay`. Verify PX4 mode/handoff evidence separately. Do not use this
preview result as flight evidence.
