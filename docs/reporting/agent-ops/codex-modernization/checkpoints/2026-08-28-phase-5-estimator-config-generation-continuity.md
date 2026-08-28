# Phase 5 Checkpoint: Estimator And Config Generation Continuity

Date: 2026-08-28
Issue: PXE-0167
Status: implementation and repository validation complete; operator acceptance pending

## Problem

Detector-assisted recovery used the normal new-target initialization path and
reset the shared Kalman filter. The operator prediction could therefore freeze
or jump after a short loss. An unrelated runtime-lifecycle defect let a process
that survived an external source update read the new retirement registry while
retaining its older defaults and schema, producing a misleading dashboard
error.

## Decision

- Keep command freshness and visual continuity separate. The first rejected
  measurement clears pursuit intent, while bounded visual recovery continues.
- Add an optional in-memory estimator snapshot/restore protocol used only when
  detector recovery re-seeds the existing target. Never persist this state.
- Commit at most one prediction per failed frame and draw that exact point.
  Prediction and tentative recovery remain follower-ineligible until a fresh
  measured update.
- Load defaults, schema, and retirements as one digest-verified generation.
  Runtime consumers use that generation consistently; disk drift produces a
  typed restart-required status and a clear dashboard message.

## Files

- `src/classes/config_service.py`
- `src/classes/api_v1_contracts.py`
- `src/classes/estimators/base_estimator.py`
- `src/classes/estimators/kalman_estimator.py`
- `src/classes/trackers/base_tracker.py`
- `src/classes/app_controller.py`
- `dashboard/src/context/PendingRestartContext.js`
- `dashboard/src/components/config/PendingRestartBanner.js`
- focused backend and dashboard tests
- tracker, Config Sync, changelog, journal, and issue-register documentation

## Validation

- Recovery/config/API focused suite: 438 passed
- Config/API follow-up: 160 passed
- Full tracker unit suite: 383 passed, 40 optional dlib skips
- Required Phase 0 gate: 73 passed
- Dashboard focused suite: 31 passed
- Active documentation consistency suite: 31 passed
- `bash scripts/check_schema.sh`: passed
- Python syntax compilation: passed
- Dashboard ESLint with zero warnings: passed
- Dashboard production build: passed
- `git diff --check`: passed

## Risks And Next Gate

The shared estimator is a bounded constant-acceleration image-plane model, not
semantic identity or learned target intent. Abrupt camera motion, turns, long
occlusion, and lookalike targets can still defeat it. No Raspberry Pi, camera,
PX4, SITL, field, or aircraft result is claimed. The next operator gate should
replay the reported CSRT loss case, verify the yellow marker advances during
short loss, confirm fresh-measurement recovery, and verify the vehicle command
preview remains neutral throughout prediction-only intervals.
