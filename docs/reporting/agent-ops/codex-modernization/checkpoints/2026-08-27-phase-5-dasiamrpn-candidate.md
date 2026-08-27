# Phase 5 DaSiamRPN Target-Test Candidate

Date: 2026-08-27

Issue: PXE-0163

Status: local software and exact-replay gates complete; visual operator and
target-hardware evidence pending

## Decision

The supplied replay exposed a tracker-provider limitation rather than a shared
recovery or estimator defect. VitTrack expanded onto the road at the
road-to-grass transition. NanoTrack continued returning success but visibly
locked to background. Relaxing PixEagle's shared gates would therefore hide a
wrong-object lock rather than improve robustness.

OpenCV DaSiamRPN is added as an optional comparison candidate. It retained the
selected trajectory across the same transition in the local visual probe and
reported low native confidence during the uncertain interval. CSRT remains the
beginner default.

## Implementation

- Added a reusable OpenCV native-score classic adapter and kept native model
  confidence as a hard gate independent of the blended PixEagle confidence.
- Added the DaSiamRPN factory provider without a private estimator, recovery
  timer, detector loop, or follower exception.
- Pinned all three OpenCV sample artifacts by URL, byte size, SHA-256, source
  revision, destination, publisher, and MIT license.
- Added a separate default-No guided setup choice and explicit Make install and
  dry-run commands. Exact verified files are reused; failure degrades only this
  optional tracker.
- Added generated schema/catalog controls, benchmark support, tests, and
  operator/developer documentation.

## Exact Replay

```text
Video:          resources/test4.mp4
Video SHA-256:  1a7d8db3bd461363c56177afde2aa9e583dbc957b08c7fd32516d3df87920b9f
Start frame:    749
Initial box:    [541, 372, 104, 59]
Updates:        500
Usable:         461 (92.2%)
Rejected:       39
First reject:   frame 815
Latency:        81.0 ms p50 / 88.4 ms p95 / 160.4 ms maximum
Host:           Linux x86_64, Python 3.12.3, OpenCV 4.13.0
```

The benchmark excludes application detector recovery, PX4, and followers. The
video is unannotated, so usable rate is not IoU accuracy or identity proof.

## Validation

```text
Installer/docs/tracker/schema suite:       542 passed / 40 optional dlib skipped
API inventory and Parameters reload:        81 passed
Config service/tracker action regression:  156 passed
Artifact checksum verification:            passed (3 files)
Generated schema and shell/Python syntax:   passed
Exact PixEagle adapter replay:              passed
```

## Remaining Evidence

- operator visual test of the refreshed authenticated browser demo;
- annotated false-lock, identity-switch, recovery, and IoU evidence;
- Raspberry Pi, Jetson, and Ubuntu actual-camera latency/cadence;
- dropped-frame, compression, distractor, and full-occlusion cases.

No SITL, HIL, PX4, service installation, field, real-aircraft, or military-grade
claim is made.
