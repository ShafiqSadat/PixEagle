# VitTrack Tracker

`VitTrack` is PixEagle's model-backed classic single-target tracker. OpenCV
VitTrack supplies each frame's bounding-box proposal and native confidence;
PixEagle applies the same freshness, motion, scale, appearance, estimator, and
bounded recovery contracts used by the other classic trackers.

It is useful as a lightweight appearance-aware comparison candidate. On the
supplied road-to-grass replay it drifted at the background transition, so it is
not the preferred candidate for that scene. It is still a short-term tracker. It cannot
prove physical identity through a full disappearance or among visually
indistinguishable targets.

## Setup

Guided Linux setup quietly downloads and verifies the default 715 KB OpenCV Zoo
model. A verified existing file is reused on update. Failure to acquire this
optional artifact leaves the other trackers available.

To install, repair, or inspect the pinned acquisition plan directly:

```bash
make install-tracker-artifacts
make tracker-artifact-plan
```

Then select `VitTrack` from the Dashboard tracker control or save:

```yaml
Tracking:
  DEFAULT_TRACKING_ALGORITHM: "VitTrack"
```

No separate dlib-style compiler or Python package is required. The active
OpenCV provider must expose `TrackerVit_create`; otherwise PixEagle reports an
actionable runtime error and another tracker can be selected.

## Artifact Contract

`configs/tracker_artifacts.json` is the source of truth for the default model's
exact URL, source commit, destination, byte size, SHA-256, publisher, and
license. Downloads are staged to a private temporary file, bounded by the
manifest size, verified before atomic publication, and recorded in
`models/.tracker-artifact-provenance.jsonl`.

Advanced deployments can use another reviewed ONNX file under `models/` by
setting both `model_path_override` and `model_sha256_override`. PixEagle rejects
unowned files, symlinks, paths outside the model store, missing digests, and
oversized artifacts.

## Configuration

```yaml
VitTrack_Tracker:
  artifact_id: "opencv_vittrack_2023sep"
  backend_id: 0
  target_id: 0
  native_score_threshold: 0.20
  model_score_weight: 0.65
  confidence_threshold: 0.40
  max_motion_per_frame: 0.60
  max_scale_change_per_frame: 0.60
  appearance_update_min_confidence: 0.60
  validation_consensus_frames: 3
```

Backend and target IDs are OpenCV DNN values; the portable default is CPU.
Change one gate at a time and compare usable-frame rate, false locks, identity
switches, recovery latency, and p50/p95 update latency on the same annotated
recording.

## Recovery And Limits

VitTrack does not run a private retry loop. A rejected measurement becomes
follower-ineligible immediately, and the application-owned classic recovery
path performs bounded local-to-global detector searches. A unique candidate
must pass appearance validation and multi-frame consensus before publication.
Ambiguous lookalikes remain rejected so a temporary distractor cannot replace
the operator-selected identity.

No tracker configuration guarantees recovery when the target is absent,
unobservable, or indistinguishable. Those cases require operator reselection or
a separately validated detector/ReID workflow. Validate on the exact camera,
target size, motion, compression, computer, and frame cadence before operational
use.

## Evidence

Use the common offline benchmark:

```bash
PYTHONPATH=src .venv/bin/python tools/benchmark_classic_tracker.py \
  --video /path/to/clip.mp4 \
  --tracker VitTrack \
  --bbox x,y,width,height \
  --annotations /path/to/annotations.json \
  --output reports/vittrack.json
```

This isolates short-term tracker measurements; it does not exercise shared
recovery, PX4, HIL, or flight behavior.

Related: [classic recovery](../01-architecture/classic-recovery.md),
[tuning](../04-configuration/tuning-guide.md), and the
[OpenCV Zoo VitTrack source](https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/object_tracking_vittrack).
