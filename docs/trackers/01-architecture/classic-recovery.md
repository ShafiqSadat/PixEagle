# Classic Tracker Recovery

PixEagle has one bounded detector-assisted recovery path for classic visual
trackers. CSRT, KCF, SparseFlow, VitTrack, DaSiamRPN, dlib, and future `BaseTracker` implementations
use this path; they do not implement private retry loops.

Smart/AI association and external gimbal providers keep provider-specific loss
handling because they do not share the same image matcher. All providers still
share the rule that predicted, tentative, cached, and lost output is
follower-ineligible.

## Ownership

The recovery contract separates five responsibilities:

1. A tracker supplies a `RecoveryHint`: a finite predicted center, the last
   confirmed box, prediction reliability, and optional exit edge.
2. A detector supplies its minimum search dimensions.
3. `tracking_recovery.build_recovery_search_plan()` spends the application-owned
   retry budget on valid local-to-global searches.
4. The detector returns spatially distinct, appearance-validated candidates and
   rejects a winner whose identity score is too close to a runner-up.
5. `AppController` preserves detector identity, reinitializes only a unique
   candidate, and waits for a fresh measured update.

Neither an estimator prediction nor a detector candidate can authorize follower
commands. Command eligibility is fail-closed from the first rejected tracker
update. A visual tracker may still report bounded `uncertain` continuity while
its configured consecutive-failure tolerance has not been exhausted; the
shared detector-recovery window starts only when its output reports
`recovery_recommended: true`. This keeps transient tracker noise from causing a
recovery storm without allowing stale data to reach the follower.

## Continuity Contract

Every standard visual output built by `BaseTracker` includes the same
diagnostic fields in `raw_data` and `metadata`:

- `continuity_state`: `inactive`, `measured`, `uncertain`, or `lost`;
- `failure_count` and `failure_threshold`: the provider's consecutive-failure
  counters and configured promotion threshold;
- `recovery_recommended`: whether the application should enter its bounded
  detector-recovery path.

`usable_for_following` remains false for every state except a fresh measured
output. The last confirmed box and estimator prediction can be drawn for
operator context during `uncertain` state, but they are display/recovery data
only. A custom tracker that does not publish this contract is handled
conservatively and enters recovery immediately, preserving compatibility with
older adapters.

## Command And Visual Lifecycles

The first rejected measurement invalidates the current pursuit intent; it does
not immediately end the operator's follow session. The active follower may
publish its declared inactive-target safe command, or the commander publishes
its configured neutral/hold defaults at the fixed command cadence. PixEagle
continues the bounded visual uncertainty/recovery lifecycle in parallel.

A fresh measured tracker output can resume pursuit. Prediction-only geometry,
the last confirmed box, and tentative detector candidates cannot. Visual
tracking stops only after its bounded recovery deadline or an explicit operator
action. Command-publication, Offboard-ownership, and PX4-link failures remain
separate terminal safety paths; estimator recovery never masks them. PX4's own
Offboard-loss timeout and action remain vehicle configuration and must be
validated for the intended airframe.

## Search Policy

Automatic recovery uses a deterministic sequence:

- begin around a reliable estimator prediction;
- otherwise begin around the last confirmed measurement;
- clamp an out-of-frame prediction to the nearest image edge;
- size the initial region from target/detector dimensions;
- expand local regions over the available local attempts;
- reserve the final attempts for full-frame search.

Every local region is positive, inside the frame, and large enough for the
detector. Missing or invalid local hints fall back to a full-frame search rather
than producing an empty ROI. The complete sequence still ends at
`Tracking.TRACKING_FAILURE_TIMEOUT`; it is not an unbounded background loop.

## Appearance Identity

The template detector keeps two bounded views:

- the immutable operator-selected template and appearance features;
- one recent view accepted only from high-confidence tracking.

Searching both views helps across scale, viewpoint, illumination, and
background transitions. Automatic tracker reinitialization restores the
original detector identity and does not learn from the tentative box. Trackers
using the shared estimator preserve its pre-loss motion state across this
re-seed, but still require a new measured tracker update before command
eligibility resumes. Only the existing high-confidence measured-update path
may refresh the recent view, so one candidate cannot silently replace the
selected target. This is a conservative online appearance aid, not semantic
identity or a guarantee against similar distractors.

## Distractor Handling

Template matching evaluates a bounded set of spatial peaks across the immutable
and trusted templates and configured scales. Overlapping proposals are merged,
each remaining candidate must independently pass visual and appearance gates,
and the best identity score must lead the runner-up by the configured margin.
If two cars or other targets remain visually indistinguishable, recovery stays
ambiguous and no tracker state is changed. A later retry can still recover the
original target because tentative candidates never update its identity model.

This is deliberately conservative. A classic appearance-only detector cannot
prove physical identity when one lookalike remains visible while the selected
target is absent. That case requires operator reselection or a separately
validated learned ReID/tracklet tracker. PixEagle does not hide that limitation
behind an automatic nearest-box rule.

## Configuration

```yaml
Tracking:
  TRACKING_FAILURE_TIMEOUT: 5.0
  REDETECTION_ATTEMPTS: 5

Detector:
  AUTO_REDETECT: true
  MIN_SEARCH_RADIUS: 50
  REDETECTION_SEARCH_RADIUS: 300
  UNCERTAINTY_SCALE_FACTOR: 2.0
  ESTIMATOR_UNCERTAINTY_THRESHOLD: 1000.0
  REDETECTION_GLOBAL_SEARCH_ATTEMPTS: 2
  REDETECTION_MAX_CANDIDATES: 5
  REDETECTION_CANDIDATE_NMS_IOU: 0.3
  REDETECTION_MIN_CONFIDENCE_MARGIN: 0.05
```

`MIN_SEARCH_RADIUS` and `REDETECTION_SEARCH_RADIUS` bound local search.
`UNCERTAINTY_SCALE_FACTOR` scales the initial radius from target extent.
`ESTIMATOR_UNCERTAINTY_THRESHOLD` prevents an uncertain estimator from taking
priority over the last confirmed box. The global-attempt count is clamped to
the total attempt budget. Candidate count bounds detector cost, NMS merges the
same target proposed by several templates/scales, and the confidence margin
controls conservative lookalike rejection.

Increasing search area, attempts, template scales, or timeout raises compute
cost and false-match exposure. Tune with annotated representative media and
report recovery rate, recovery latency, and wrong-object locks together.

## Extension Contract

A new classic tracker normally needs only `BaseTracker`'s inherited
`get_recovery_hint()` and `get_tracking_continuity()` contract. A tracker with
an internal estimator, such as KCF, should override
`is_recovery_prediction_reliable()` using its own covariance contract. It must
increment/reset `failure_count` consistently for consecutive measurements; the
base output then supplies the shared recovery decision.

A new detector may override:

- `get_recovery_search_requirements()`;
- `propose_recovery()` for typed multi-candidate evidence;
- `snapshot_identity_state()` / `restore_identity_state()`.

The detector must reject invalid image regions and return a candidate only after
its own appearance/confidence validation. It must not start another retry timer
or publish tracker/follower state.

## Limits And Evidence

Template recovery can reacquire a previously observed visual appearance. It
cannot guarantee identity through long full occlusion, severe appearance
change, repeated similar objects, or a target that returns after the bounded
deadline. Those scenarios may require a trained detector, association/ReID, or
operator reselection and must be measured on the intended camera and hardware.

Primary design references:

- [Forward-Backward Error: Automatic Detection of Tracking Failures](https://cmp.felk.cvut.cz/ftp/articles/matas/kalal-2010-fb_track-icpr.pdf)
- [Tracking-Learning-Detection](https://doi.org/10.1109/TPAMI.2011.239)
- [OpenCV template matching](https://docs.opencv.org/4.x/de/da9/tutorial_template_matching.html)
- [Siam R-CNN: Visual Tracking by Re-Detection](https://openaccess.thecvf.com/content_CVPR_2020/html/Voigtlaender_Siam_R-CNN_Visual_Tracking_by_Re-Detection_CVPR_2020_paper.html)
- [Distractor-Aware Fast Tracking via Dynamic Convolutions and MOT Philosophy](https://openaccess.thecvf.com/content/CVPR2021/html/Zhang_Distractor-Aware_Fast_Tracking_via_Dynamic_Convolutions_and_MOT_Philosophy_CVPR_2021_paper.html)

Related: [Tracker architecture](README.md),
[tuning guide](../04-configuration/tuning-guide.md), and
[SparseFlow](../02-reference/sparse-flow-tracker.md), and
[VitTrack](../02-reference/vittrack-tracker.md), and
[DaSiamRPN](../02-reference/dasiamrpn-tracker.md).
