# Sparse Flow Tracker

`SparseFlow` is a classic, model-free visual tracker for textured single
targets. It uses OpenCV primitives already installed by PixEagle Core; no AI
model or extra setup step is required.

The implementation is complete and available as a target-test backend. This is
not a claim of parity with a commercial tracker, identity continuity through
full occlusion, or field validation. Validate it on recordings from the
intended camera and computer before operational use.

## Select It

Choose **Sparse Flow** in the Dashboard Tracker control. The selection is
applied immediately and saved as the restart default. The equivalent local
override is:

```yaml
Tracking:
  DEFAULT_TRACKING_ALGORITHM: "SparseFlow"
```

Select a target exactly as with CSRT or KCF. A larger box can provide more
texture, but excessive background inside the box can dominate point motion.

## Measurement Pipeline

For each accepted frame, the tracker:

1. seeds bounded Shi-Tomasi and/or grid points inside the target;
2. tracks them with pyramidal Lucas-Kanade flow in both directions;
3. rejects invalid, out-of-frame, and high forward-backward-error points;
4. estimates a partial-affine transform with RANSAC and a median-translation
   fallback;
5. checks scale, rotation, appearance, shared motion, and frame-boundary gates;
6. commits the new frame, points, box, and adaptive template only after every
   gate accepts the measurement;
7. reseeds points after an accepted update when density or cadence requires it.

`propose()` is non-mutating and `commit()` is revision-guarded. A failed
candidate therefore cannot corrupt the last accepted optical-flow state.

## Loss And Recovery

`SparseFlow` reports failure when it cannot defend a fresh measurement. The
shared PixEagle lifecycle then owns estimator prediction and bounded
detector-assisted recovery. There is no second tracker-local Kalman filter,
detector loop, or follower policy.

That shared recovery clips out-of-frame predictions, expands target-relative
local searches, and uses final full-frame attempts. It also preserves the
operator-selected detector identity when a candidate reinitializes SparseFlow.
See [Classic tracker recovery](../01-architecture/classic-recovery.md).

On the first rejected frame:

- the last confirmed box may remain visible for diagnostics;
- output is marked prediction-only/stale;
- `usable_for_following` is `false`;
- follower commands cannot be authorized from that output.

Long occlusion, similar-object crossings, abrupt frame jumps, severe blur, and
large target appearance changes still require scenario evidence and may need a
detector-backed SmartTracker instead.

## Configuration

Checked-in defaults and validated ranges live in
`configs/config_default.yaml` and `configs/config_schema.yaml`.

```yaml
SparseFlow_Tracker:
  feature_strategy: "auto"       # auto, gftt, grid
  max_points: 100
  min_points: 8
  lk_window_size: 21
  lk_max_level: 3
  fb_error_ratio: 0.025
  min_inlier_ratio: 0.55
  max_scale_change_per_frame: 0.35
  max_rotation_degrees_per_frame: 35.0
  min_appearance_confidence: 0.25
  confidence_threshold: 0.45
  reseed_interval_frames: 5
  failure_threshold: 5
```

Advanced settings are available in Settings under **Sparse Flow Tracker** and
take effect after the tracker restarts. Tune one parameter group at a time on
fixed media. Do not lower rejection gates based only on how long a box remains
visible; also measure false locks and identity switches.

## Diagnostics

`TrackerOutput` reports:

- retained/source point counts;
- forward-backward threshold and median error;
- geometry inlier ratio and transform model;
- scale and image-plane rotation;
- appearance confidence and point-reseed status;
- measurement, stale, and follower-eligibility state.

These fields are evidence inputs, not universal quality ratings.

## Repeatable Benchmark

Run the short-term backend on the same video and initial box used for another
tracker:

```bash
PYTHONPATH=src .venv/bin/python tools/benchmark_classic_tracker.py \
  --video /path/to/clip.mp4 \
  --tracker SparseFlow \
  --bbox x,y,width,height \
  --output reports/sparse-flow.json
```

Optional JSON annotations add IoU, center precision, and false-lock metrics.
The runner intentionally excludes AppController prediction and re-detection;
use system-level validation for recovery and follower proofs.

## Acceptance Boundary

Before operational use, benchmark the intended camera path, target size,
compression, blur, camera motion, frame cadence, occlusion, distractors, and
hardware. Raspberry Pi, Jetson, and x86 results are not interchangeable.

See the [research and promotion plan](../05-development/sparse-flow-tracker-proposal.md)
for evidence requirements and future candidates.

## References

- [Forward-Backward Error paper](https://cmp.felk.cvut.cz/ftp/articles/matas/kalal-2010-fb_track-icpr.pdf)
- [OpenCV sparse optical-flow APIs](https://docs.opencv.org/4.x/dc/d6b/group__video__track.html)
- [Tracker testing](../05-development/testing-trackers.md)
