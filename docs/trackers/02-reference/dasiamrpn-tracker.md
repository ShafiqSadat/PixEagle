# DaSiamRPN Tracker

`DaSiamRPN` is an optional model-backed classic single-target tracker. OpenCV's
runtime supplies distractor-aware bounding-box proposals and a native score;
PixEagle applies the same motion, scale, freshness, estimator, consensus, and
bounded recovery contracts used by the other classic trackers.

It is a heavier comparison candidate for camera motion and background changes.
It remains a short-term visual tracker: it cannot prove physical identity after
full disappearance or among indistinguishable targets.

## Setup

Guided Linux setup offers one default-No prompt because the three models total
about 155 MiB. Install, repair, or preview them directly:

```bash
make install-dasiamrpn-artifacts
make dasiamrpn-artifact-plan
```

Then select `DaSiamRPN` in the Dashboard or save it as the default tracker. A
missing artifact disables only this tracker.

## Artifact Contract

`configs/tracker_artifacts.json` pins all three URLs, byte sizes, SHA-256
digests, source revision, publisher, destination, and MIT license. Downloads
are bounded, staged privately, verified, and published atomically. Exact files
are reused during setup and update.

Advanced deployments may override each model with an owner-controlled regular
file under `models/` and its matching SHA-256. Partial overrides, symlinks,
external paths, digest mismatches, and oversized files are rejected.

## Configuration

```yaml
DaSiamRPN_Tracker:
  model_artifact_id: "opencv_dasiamrpn_model"
  kernel_r1_artifact_id: "opencv_dasiamrpn_kernel_r1"
  kernel_cls1_artifact_id: "opencv_dasiamrpn_kernel_cls1"
  backend_id: 0
  target_id: 0
  native_score_threshold: 0.20
  model_score_weight: 0.80
  use_shared_appearance_validation: false
  confidence_threshold: 0.35
  max_motion_per_frame: 0.65
  max_scale_change_per_frame: 0.65
  validation_consensus_frames: 3
```

The native score is a hard gate. `model_score_weight` controls the confidence
blend only after that gate passes. The default leaves shared template
appearance validation off because the Siamese distractor model owns appearance;
motion, scale, consensus, freshness, and application recovery remain active.

Backend and target IDs are advanced OpenCV DNN controls. Keep the portable CPU
defaults unless an exact hardware benchmark proves another combination.

## Evidence And Limits

On `resources/test4.mp4` from frame 749 with initial box
`[541, 372, 104, 59]`, the PixEagle adapter produced 461 usable measurements
from 500 updates. It rejected 39 native low-score frames around the difficult
road-to-grass transition and subsequently resumed measured output. Median
update latency was 81.0 ms and p95 was 88.4 ms on the tested x86_64 VPS.

This unannotated replay is comparative software evidence only. It does not
prove bounding-box accuracy, identity continuity, Raspberry Pi/Jetson cadence,
camera performance, flight behavior, or field suitability. Benchmark the exact
camera, target size, compression, motion, and computer before use.

```bash
PYTHONPATH=src .venv/bin/python tools/benchmark_classic_tracker.py \
  --video /path/to/clip.mp4 \
  --tracker DaSiamRPN \
  --bbox x,y,width,height \
  --annotations /path/to/annotations.json \
  --output reports/dasiamrpn.json
```

Related: [classic recovery](../01-architecture/classic-recovery.md),
[tuning](../04-configuration/tuning-guide.md), the
[OpenCV sample](https://github.com/opencv/opencv/blob/816851c99962dce0e661ce0401393f52818e0b61/samples/dnn/dasiamrpn_tracker.cpp),
and the [original DaSiamRPN project](https://github.com/foolwood/DaSiamRPN).
