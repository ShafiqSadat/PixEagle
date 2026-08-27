# Sparse Flow Tracker Plan And Evidence

Status: target-test backend available; target-hardware field-validation evidence pending

Date: 2026-08-25

Issue: PXE-0158

## Decision

The customer-supplied reel is consistent with a custom **classic short-term
sparse optical-flow tracker** in the MedianFlow family. It is not evidence of a
YOLO detector, a learned tracker, sensor fusion, or a public Teravolt software
package.

PixEagle now provides a tracker named `SparseFlow`, implemented from published
methods with maintained OpenCV primitives. It does not copy the product name
or claim Teravolt equivalence. It is selectable for controlled comparison but
is not the checked-in default or a field-readiness claim.

No new runtime dependency is required for the first candidate. PixEagle's Core
OpenCV provider already supplies pyramidal Lucas-Kanade flow, feature selection,
and robust geometric estimation.

## What The Reel Shows

The operator-supplied screen recording visibly contains:

- a C++ class named `MedianFlowTracker`;
- a forward-backward error parameter named `fbErrorMaxPx`;
- a `revalidated` result flag;
- a `High-Speed Mono Tracker` display;
- a point count near 100, confidence, and approximately 27 FPS;
- a green bounding box around a textured fixed-wing aircraft.

Those clues fit a grid or feature set tracked by forward and backward optical
flow, followed by rejection of inconsistent points and a robust box update.
The `revalidated` flag may indicate an appearance or local-reacquisition check,
but that is an inference. The reel does not reveal its implementation, license,
training data, complete failure behavior, camera calibration, or recovery after
full occlusion.

Teravolt's public company material describes an on-device ARM/global-shutter
tracker and reports a 100+ FPS hardware path, while the recorded demonstration
was capped near 30 FPS. It does not publish the tracker source or enough detail
to reproduce the exact product. Camera exposure, optics, global-shutter capture,
target pixel size, and compression are part of that result; software alone
cannot guarantee it on arbitrary video.

## Published Design Basis

The original MedianFlow method places points in the target box, tracks them
with pyramidal Lucas-Kanade optical flow in both temporal directions, rejects
unreliable trajectories, and estimates translation and scale from robust
statistics. The paper reports that forward-backward error combined with an
appearance check was its strongest tested variant.

OpenCV still carries a legacy contrib `TrackerMedianFlow` implementation. It is
useful as a benchmark reference, but it should not be PixEagle's product
backend: the legacy wrapper exposes little quality telemetry, makes recovery
decisions opaque, and does not fit PixEagle's measured/tentative/predicted/lost
contract well.

The PixEagle backend composes maintained OpenCV primitives:

1. Convert each accepted frame to 8-bit grayscale.
2. Seed a bounded set of well-distributed points inside an eroded target ROI.
3. Run pyramidal Lucas-Kanade flow forward and backward.
4. Reject invalid, out-of-frame, and high-error trajectories using ROI-scaled
   forward-backward thresholds.
5. Estimate translation, scale, and rotation with a robust partial-affine fit,
   falling back to median translation when the fit is unavailable.
6. Derive confidence from point retention, normalized forward-backward error,
   appearance consistency, and transform residual.
7. Reseed only inside accepted candidate geometry and commit adaptation only
   after shared gates accept the measurement.
8. Report failure when a fresh measurement is not defensible.

The tracker must not publish its own predicted box as a measurement.

## PixEagle Integration Boundary

`SparseFlow` is one measurement provider behind `BaseTracker` and
`TrackerOutput`. Existing shared components remain authoritative:

- `AppController` owns target loss and the bounded recovery window.
- The shared estimator supplies overlay/search prediction only.
- Detector-assisted re-detection owns long-term reacquisition.
- `TrackerRuntimeStatus` owns command freshness.
- Followers accept only current, validated measurements.
- The final circuit breaker and command-preview sink remain unchanged.

This boundary prevents a second hidden Kalman filter, recovery state machine,
or follower-safety policy from growing inside the tracker. It also lets the
same recovery logic serve CSRT, KCF, Sparse Flow, dlib, and future measurement
providers.

Background-flow camera-motion compensation is a separate experiment. It may
help during aggressive ego motion, but a foreground-contaminated transform can
make tracking worse. Add it only if the benchmark shows a repeatable gain.

## Implementation Status

### Completed

- Commit-gated sparse-flow core with no PixEagle lifecycle dependencies.
- `BaseTracker` adapter, factory/catalog registration, generated Settings
  controls, and Core OpenCV capability checks.
- Deterministic translation, occlusion, stale-proposal, confidence, output, and
  factory tests.
- Equal-input short-term benchmark runner for CSRT, KCF, Sparse Flow, VitTrack,
  and dlib,
  with optional ground-truth metrics.
- Standard measured/prediction-only/follower-eligibility output; no tracker-local
  prediction or recovery state machine.

### Remaining Promotion Evidence

- Annotated UAV123/UAV20L and representative customer clips.
- Full AppController recovery evidence on scene jumps, occlusion, and
  distractors.
- Raspberry Pi 5, supported Jetson, and Ubuntu x86_64 camera-path latency and
  continuity reports.
- Direct equal-input comparison with CSRT/KCF/dlib on the intended scenarios.

Do not start with a custom C++ extension. Profile first; add a reviewed native
extension only if Python orchestration is a measured bottleneck on target
hardware.

## Future Candidates

These are benchmark TODOs, not promised improvements:

- **Sparse RLOF:** OpenCV's robust local flow may improve outlier handling, but
  its acceleration and latency characteristics differ across x86 and ARM.
- **Camera-motion compensation:** background-flow stabilization may help during
  aggressive ego motion; foreground contamination and parallax can also make it
  worse, so keep it outside the default until measured.
- **TAPIR/BootsTAPIR:** causal learned point tracking is a strong Smart-backend
  candidate for occlusion, but requires model/runtime, accelerator, and license
  acceptance rather than being hidden inside a classic tracker.
- **CoTracker-family models:** useful research comparators for long trajectories
  and visibility, subject to checkpoint licensing, memory, and causal-latency
  review.
- **Learned single-object trackers:** transformer/Siamese SOT backends may add
  appearance robustness, but need trusted model supply, target-hardware
  profiling, and the same fail-closed output contract.
- **Native C++ core:** consider only if profiling proves Python call orchestration
  is the bottleneck after OpenCV kernels and frame transport are accounted for.

## Evidence And Promotion Gate

The Instagram screen recording is useful design evidence but is not a benchmark:
it is re-recorded, compressed, perspective-distorted, and does not show complete
failure/recovery cases. Equal or better performance cannot be guaranteed from
that reel.

Promotion requires:

- deterministic translation, scale, rotation, illumination, blur, dropped-frame,
  frame-jump, edge-exit, partial/full-occlusion, and distractor tests;
- UAV123/UAV20L and representative customer clips with fixed ground truth;
- equivalent 5, 15, and 30 FPS trajectories plus irregular cadence;
- success AUC/IoU, center precision, false-lock/identity-switch, time-to-loss,
  bounded recovery rate/time, and confidence-calibration results;
- p50/p95 update latency, throughput, CPU, memory, and frame-age results;
- Raspberry Pi 5, supported Jetson, and Ubuntu x86_64 evidence using the actual
  camera/RTSP path where applicable;
- explicit proof that non-measured states never enable follower commands.

The candidate should become official only when it materially improves the
agreed aerial scenarios or provides a measured speed/quality tradeoff that
justifies another backend. Marketing claims must state the tested hardware,
video, configuration, and evidence artifact.

## Inputs Needed From The Customer

- the original source clip rather than the Instagram re-recording;
- camera model, shutter type, lens, exposure, resolution, and frame rate;
- target hardware and expected compute budget;
- representative target size, motion, occlusion, and recovery scenarios;
- initial boxes or ground-truth annotations;
- permission to retain and use the media for development/benchmark evidence.

Without those inputs, PixEagle can build a defensible general tracker but cannot
validate parity with the demonstrated system.

## Primary References

- [Forward-Backward Error: Automatic Detection of Tracking Failures](https://cmp.felk.cvut.cz/ftp/articles/matas/kalal-2010-fb_track-icpr.pdf)
- [Tracking-Learning-Detection thesis](https://cmp.felk.cvut.cz/~matas/papers/kalal-2010-phd.pdf)
- [OpenCV sparse optical-flow APIs](https://docs.opencv.org/4.x/dc/d6b/group__video__track.html)
- [OpenCV Shi-Tomasi feature selection](https://docs.opencv.org/4.x/d4/d8c/tutorial_py_shi_tomasi.html)
- [OpenCV legacy MedianFlow source](https://github.com/opencv/opencv_contrib/blob/4.x/modules/tracking/src/trackerMedianFlow.cpp)
- [OpenCV Sparse RLOF](https://docs.opencv.org/4.x/d2/d84/group__optflow.html)
- [TAPIR/BootsTAPIR](https://github.com/google-deepmind/tapnet)
- [CoTracker](https://github.com/facebookresearch/co-tracker)
- [UAV123 and UAV20L benchmark](https://ivul.kaust.edu.sa/benchmark-and-simulator-uav-tracking-dataset)
- [Teravolt](https://www.teravolt.in/)
- [Teravolt Labs public company activity](https://www.linkedin.com/company/teravoltlabs/)
- [Basler global and rolling shutter comparison](https://docs.baslerweb.com/electronic-shutter-types)

## Related Work

- [Tracker architecture](../01-architecture/README.md)
- [Tracker testing](testing-trackers.md)
- [Tracker best practices](best-practices.md)
- [Smart tracker](../02-reference/smart-tracker.md)
- PXE-0131 in the modernization issue register covers cadence-independent aerial
  lifecycle and recovery acceptance shared by all trackers.
