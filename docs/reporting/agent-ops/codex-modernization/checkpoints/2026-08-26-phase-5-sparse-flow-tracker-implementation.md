# Phase 5 Sparse Flow Tracker Target-Test Implementation

Date: 2026-08-26

Issue: PXE-0158

Status: local software release gates complete; target promotion evidence pending

## Scope

- Add one opt-in classic tracker that is independent of model runtimes.
- Preserve the existing tracker, estimator, recovery, freshness, and follower
  ownership boundaries.
- Expose advanced parameters through the generated Settings schema without
  changing the beginner default or adding an installer question.
- Add repeatable short-term benchmark tooling and document stronger future
  candidates without claiming unproved performance.

## Implementation

- `SparseFlowCore` proposes frame-to-frame measurements using Shi-Tomasi/grid
  points, pyramidal Lucas-Kanade forward/backward flow, partial-affine RANSAC,
  median-translation fallback, appearance correlation, and adaptive reseeding.
- Proposals do not mutate accepted state. `commit()` validates the proposal
  revision and confidence before publishing the next gray frame, points, box,
  and adaptive appearance template together.
- `SparseFlowTracker` adapts that measurement to `BaseTracker` and
  `TrackerOutput`. The shared motion, scale, boundary, estimator, detector
  recovery, and freshness contracts remain authoritative.
- `SparseFlow` is registered in the runtime factory and canonical tracker
  catalog. Generated Settings fields use `tracker_restart`; switching the
  tracker does not require a process reboot. CSRT remains the default.
- Core setup's existing OpenCV provider now verifies the three required flow
  primitives. No Python package, native extension, model, or setup prompt was
  added.

## Safety Contract

- The first rejected frame increments the failure state and publishes
  `prediction_only`, `data_is_stale`, and `usable_for_following: false`.
- The tracker does not promote its last box or estimator prediction into a new
  measurement.
- AppController retains the only bounded detector-recovery lifecycle.
- Follower, command-preview, circuit-breaker, MAVSDK, and PX4 code paths were
  not changed by this slice.

## Validation

```text
Phase 0 repository gate:                509 passed
Focused tracker/base/catalog gate:      120 passed, 2 skipped
Provider/schema/benchmark gate:         71 passed
Generated schema:                       40 sections / 553 parameters, current
Full non-hardware backend gate:          3,713 passed, 50 skipped, 1 deselected
Dashboard:                              402 passed; lint and build passed
Python syntax/undefined-name gate:       passed (0 findings)
Shell syntax and API candidates:         passed
git diff --check:                        passed
```

The skips are the repository's optional dlib tests because dlib is not
installed in this host environment. No SITL, PX4, HIL, hardware, or manual test
was run.

## Supplied-Reel Smoke Probe

The benchmark used the operator-supplied 720x1280, 30 FPS recording with SHA-256
`585770a4e4460264c2d8f8ca92dd4defaaf0ad53f830d18698a9a180235738c5`, start
frame `60`, and initial box `[330, 590, 110, 50]`.

| Run | Usable / Total | First Failure | p50 / p95 Update |
| --- | --- | --- | --- |
| Initial continuity probe | 120 / 120 | None | 5.21 / 21.47 ms |
| Full remainder | 203 / 518 | Frame 264 | 5.24 / 18.30 ms |

Environment: Python 3.12.3, OpenCV 4.13.0, Linux x86_64. The recording has no
ground truth, and the runner intentionally excludes AppController prediction
and detector recovery. Visual inspection indicates that the full-run failure
coincides with the later abrupt target/scene transition and remains fail-closed,
but that is qualitative only. These numbers do not establish accuracy,
identity continuity, hardware performance, field readiness, or parity with the
system shown in the reel.

## Evidence Paths

- `src/classes/trackers/sparse_flow_core.py`
- `src/classes/trackers/sparse_flow_tracker.py`
- `tests/unit/trackers/test_sparse_flow_core.py`
- `tests/unit/trackers/test_sparse_flow_tracker.py`
- `tests/test_benchmark_classic_tracker.py`
- `tools/benchmark_classic_tracker.py`
- `docs/trackers/02-reference/sparse-flow-tracker.md`
- `docs/trackers/05-development/sparse-flow-tracker-proposal.md`

## Remaining Risks And Next Slice

- Add annotated UAV123/UAV20L and representative customer sequences, then
  compare CSRT, KCF, Sparse Flow, and dlib on identical inputs.
- Measure false locks, identity switches, recovery, cadence variation, dropped
  frames, CPU/memory, and end-to-end frame age.
- Collect Raspberry Pi 5, supported Jetson, Ubuntu x86_64, and actual camera or
  RTSP evidence before promoting it to field-validated or publishing performance
  claims.
- Evaluate RLOF, camera-motion compensation, TAPIR/BootsTAPIR, CoTracker, and
  learned single-object trackers only as separate benchmarked backends.
