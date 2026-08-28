# Phase 5 Checkpoint: Shared Tracker Continuity

Date: 2026-08-28
Issue: PXE-0166
Status: implementation and repository validation complete; operator acceptance pending

## Problem

The visual tracker contract correctly made the first rejected measurement
ineligible for follower commands, but AppController immediately interpreted the
same event as terminal target loss. CSRT therefore entered detector recovery
before its configured consecutive-failure tolerance could absorb a transient
OpenCV rejection. The resulting recovery/reinitialization churn was visible as
rapid target loss, especially on the CPU path.

## Decision

- Keep command freshness fail-closed on the first rejected measurement.
- Let every `BaseTracker` publish `continuity_state`, normalized failure
  counters, and `recovery_recommended` in both output metadata containers.
- Keep transient `uncertain` frames in the normal tracker loop and draw the last
  confirmed geometry/estimator prediction for operator context only.
- Start the existing bounded detector-recovery state machine only at the
  provider's configured failure threshold. Once started, its original deadline
  remains authoritative until a fresh measurement or terminal timeout.
- Treat missing or malformed continuity metadata as immediate recovery for
  compatibility and safety. No tracker-specific controller branch was added.

## Scope

The shared BaseTracker path covers CSRT, KCF, SparseFlow, VitTrack, DaSiamRPN,
dlib, and future visual adapters that use the standard output builder. Smart
and external gimbal providers keep their existing provider-specific contracts.

## Validation

- Focused tracker/controller suite: 316 passed
- Full tracker suite: 380 passed, 40 skipped
- Required Phase 0 guardrail target: 509 passed, with one existing
  `StarletteDeprecationWarning`
- `bash scripts/check_schema.sh`: passed
- Python syntax compilation for the touched runtime modules: passed
- `git diff --check`: passed

The standard `make test` target was intentionally interrupted after 239 tests
passed (1 deselected) because its 3,820-test integration-heavy run was still
progressing after more than two minutes. It reported no test failure before
interruption; the focused, tracker, and Phase 0 gates above are the acceptance
evidence for this slice.

No Raspberry Pi, camera, PX4, SITL, field, or aircraft result is claimed. The
next operator test should compare CSRT continuity and recovery latency on the
same replay/configuration used for the regression report.
