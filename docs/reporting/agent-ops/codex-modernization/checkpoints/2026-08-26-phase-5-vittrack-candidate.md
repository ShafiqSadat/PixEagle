# Phase 5 VitTrack Target-Test Candidate

Date: 2026-08-26

Issue: PXE-0162

Status: local software gates complete; operator and target-hardware evidence pending

## Scope

- Add one opt-in appearance-aware classic tracker without changing the beginner
  default or introducing another setup question.
- Preserve one shared classic tracker validation, recovery, freshness, and
  follower-safety boundary.
- Make external model acquisition exact, licensed, verifiable, reusable, and
  non-fatal to the rest of PixEagle.
- Keep tuning and future model/backend changes schema-driven.

## Implementation

- `VitTrackTracker` adapts OpenCV VitTrack proposals and native confidence to
  PixEagle's existing validated classic measurement lifecycle. It adds no
  private estimator, retry timer, detector loop, or follower exception.
- The factory/catalog and generated Settings schema expose `VitTrack` as a
  saved runtime-selectable classic tracker. CSRT remains the default.
- `tracker_artifacts.json` pins the exact OpenCV Zoo source commit, URL, size,
  SHA-256, destination, publisher, and Apache-2.0 license.
- The installer bounds and hashes the download before atomic publication,
  records provenance, reuses verified content, and never overwrites a
  mismatched file. A setup failure marks only VitTrack degraded.
- Advanced custom models require an owner-controlled regular file under
  `models/` and an explicit digest. Symlinks, external paths, missing hashes,
  wrong owners, and oversized artifacts are rejected.

## Safety Contract

- Every rejected update is immediately stale and follower-ineligible.
- Shared application-owned detector recovery remains bounded and requires a
  unique appearance-validated candidate plus tracker consensus.
- Native model confidence cannot bypass motion, scale, appearance, freshness,
  circuit-breaker, or follower command gates.
- VitTrack cannot guarantee physical identity when the target is absent or
  indistinguishable; operator reselection or a separately validated ReID
  provider remains required.

## Validation

```text
Focused tracker/artifact/schema/benchmark: 148 passed, 2 skipped
Tracker/recovery/controller/detector:       583 passed, 40 skipped
Installer/config/docs:                     123 passed
Required Phase 0 gate:                     509 passed
Generated schema:                          41 sections / 576 parameters, current
Artifact verify and dry-run:               passed
Python and shell syntax:                   passed
git diff --check:                          passed
```

The skips are optional dlib tests because dlib is unavailable in this host
environment. A redundant full repository sweep was stopped at 558 passed,
1 skipped, and 1 deselected to keep the requested test handoff bounded; CI
remains responsible for the complete matrix. No PX4, SITL, HIL, hardware,
service-installation, or real-aircraft action was performed.

## Local Model Smoke Probe

The repeatable benchmark used `resources/test4.mp4`, SHA-256
`1a7d8db3bd461363c56177afde2aa9e583dbc957b08c7fd32516d3df87920b9f`,
start frame `1179`, initial box `[488, 282, 150, 71]`, and 80 updates.

```text
Usable measurements: 80 / 80
First failure:        none
Update latency:       5.75 ms p50 / 7.77 ms p95 / 9.46 ms max
Environment:          Python 3.12.3, OpenCV 4.13.0, Linux x86_64
```

The clip has no committed ground-truth annotations and the benchmark excludes
application recovery. These numbers establish only local runtime operation and
cost, not accuracy, identity continuity, aerial performance, or field readiness.

## Evidence Paths

- `configs/tracker_artifacts.json`
- `src/classes/tracker_artifacts.py`
- `src/classes/trackers/vittrack_tracker.py`
- `scripts/setup/install-tracker-artifacts.py`
- `tests/test_tracker_artifact_setup.py`
- `tests/unit/trackers/test_vittrack_tracker.py`
- `tools/benchmark_classic_tracker.py`
- `docs/trackers/02-reference/vittrack-tracker.md`

## Remaining Evidence

- Complete the authenticated public browser visual test.
- Compare annotated recovery, false locks, identity switches, cadence variation,
  and end-to-end latency against CSRT, KCF, SparseFlow, and dlib.
- Collect Raspberry Pi, Jetson, Ubuntu, and actual camera/RTSP evidence before
  any field-performance claim or final tracker recommendation.
