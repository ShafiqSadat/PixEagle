# Phase 5 Checkpoint: CSRT Continuity Calibration

Date: 2026-08-28
Issue: PXE-0168

## Scope

Reconstruct the latest VPS CSRT loss, separate adapter rejection from native
OpenCV failure, and correct only the reusable continuity contract.

## Evidence

- Runtime: `pixeagle_manual_7e4592b3-128f-42f6-8267-65abb354b05a`
- Source media: `resources/test4.mp4`, 1280x720, 30 fps
- Replayed selection: frame 246, bounding box `(648, 447, 103, 59)`
- Existing strict gate rejected candidates with combined confidence near
  `0.80` and appearance near `0.61`, before native CSRT failure.
- A separate `0.25` continuity floor retained those measurements and rejected
  the later clear mismatch near `0.14`. Dynamic catch-up still exposed native
  CSRT loss around frame 488.
- At a three-frame cadence, the prior `0.70` gate produced `38` measured,
  `37` appearance-rejected, `5` consensus-pending, and `71` native-failed
  updates. The new floor produced `74` measured, `6` appearance-rejected, and
  the same `71` native-failed updates beginning at frame 489.
- At full capture cadence, the new floor produced `248` measured updates before
  the unannotated scene's later appearance collapse. This does not establish
  that the resulting box retained the intended physical target.

The media has no identity annotations. These results compare process behavior;
they do not prove target identity, field accuracy, or military-grade tracking.

## Changes

- Added one schema-backed CSRT-family short-term appearance floor.
- Retained the strict global threshold for detector-assisted re-acquisition.
- Published shared failure reasons and the effective appearance floor.
- Updated focused tests and operator configuration/reference documentation.

## Validation

- Focused CSRT/base/model-backed tracker tests: `156 passed`
- Complete tracker suite: `385 passed`, `40` optional dlib skips
- Config/schema lifecycle tests: `201 passed`
- Required Phase 0 API/config gate: `73 passed`
- Active infrastructure documentation: `31 passed`
- Generated schema, Python syntax, and diff checks: passed

## Remaining Gates

Annotated identity/recovery scoring, target-camera cadence, Raspberry Pi,
Jetson, PX4, SITL, and field acceptance remain pending.
