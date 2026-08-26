# Phase 5 Shared Classic Recovery

Date: 2026-08-26

Issue: PXE-0160

Status: local software gates complete; operator visual test pending

## Scope

- Repair invalid recovery geometry after a classic tracker loses its target.
- Give every `BaseTracker` visual provider one bounded local-to-global policy.
- Preserve operator-selected appearance identity during automatic recovery.
- Reject ambiguous lookalike candidates instead of silently switching targets.
- Keep predictions and tentative candidates ineligible for follower commands.

## Implementation

- `tracking_recovery.py` defines typed tracker hints, detector requirements,
  deterministic search plans, candidates, and detector outcomes.
- Local regions expand around a reliable estimate or last measured box. Final
  configured attempts search the full frame, and every ROI is clipped and large
  enough for the active detector.
- Template recovery searches immutable and trusted high-confidence views across
  configured scales, normalizes method scores, extracts bounded spatial peaks,
  merges overlapping proposals, and validates appearance independently.
- A candidate is accepted only when its identity score leads a validated
  runner-up by the configured margin. Ambiguous attempts do not reinitialize
  the tracker or mutate detector identity.
- Reinitialization restores detector identity and moves geometry only. The
  tentative box is not learned; trusted appearance updates remain owned by the
  existing high-confidence measured-update path.

## Validation

```text
Focused detector/recovery/controller: 199 passed
Core/controller/tracker/detector:      1,321 passed, 40 skipped
Required Phase 0 gate:                 73 passed
Version/config/recovery recheck:       59 passed
Documentation consistency:            31 passed
Generated schema:                     40 sections / 557 parameters, current
Python syntax/import checks:           passed
git diff --check:                      passed
```

The skips are optional dlib tests because dlib is unavailable in this host
environment. Deterministic tests cover out-of-frame estimates, expanding and
global search, far target re-entry, duplicate-proposal suppression, two
identical visible targets, ambiguity rejection, immutable identity retention,
and no tracker mutation on an ambiguous result.

## Design Evidence

- Forward/backward error supports explicit tracker-failure detection.
- TLD and long-term-tracking evaluations support bounded image-wide
  re-detection and conservative model updates.
- Siam R-CNN and DMTrack support explicit candidate/distractor reasoning rather
  than selecting one unconstrained maximum.

The implemented classic path uses the safe, CPU-bounded subset of those
principles. Learned ReID and distractor tracklets are deferred as PXE-0161.

## Files

- `src/classes/tracking_recovery.py`
- `src/classes/trackers/base_tracker.py`
- `src/classes/trackers/kcf_kalman_tracker.py`
- `src/classes/detectors/base_detector.py`
- `src/classes/detectors/template_matching_detector.py`
- `src/classes/app_controller.py`
- `configs/config_default.yaml`
- `configs/config_schema.yaml`
- `scripts/generate_schema.py`
- `tests/unit/trackers/test_tracking_recovery.py`
- `tests/unit/detectors/test_detector_contract.py`
- `tests/unit/core_app/test_app_controller_offboard_safety.py`
- `docs/trackers/01-architecture/classic-recovery.md`

## Remaining Evidence

- Run the authenticated public browser demo for operator visual review.
- Measure recovery rate, latency, and wrong-object locks on annotated aerial
  clips and Raspberry Pi/Jetson/Ubuntu target hardware.
- Do not infer semantic identity, ReID, PX4, flight, field, or military-grade
  performance from deterministic software tests or the public demo.
