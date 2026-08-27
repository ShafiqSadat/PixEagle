# Phase 5 Bounded-Latency Tracking UI

Date: 2026-08-27

Issue: PXE-0164

Status: local and refreshed public browser gates complete; operator tracking
continuity test pending

## Problem

DaSiamRPN construction completed in roughly one tenth of a second, but its
CPU-heavy full loop made OpenCV video-file playback process every frame below
wall clock. The browser's JPEG decoder retained only the newest pending frame,
but ordered WebSocket transmission had no rendered-frame feedback and could
still accumulate transport latency. A semantic tracker icon was also rendered
as literal text in the compact selector.

## Decision

- Keep one pipeline timing authority. OpenCV local files now discard only
  accumulated overdue frames in `REALTIME`; deterministic replay and maximum
  throughput preserve capture order, and GStreamer keeps its clocked leaky
  appsink.
- Let dashboard WebSocket clients negotiate one exact JPEG in flight. Render
  or decode failure acknowledges that frame before the server samples the
  newest publication. Non-negotiating native and QGC clients remain compatible.
- Render schema icon keys through one bounded component and link the compact
  classic-tracker, Smart-model, and follower controls to canonical references.
- Do not add a road-marking rule or enable duplicate strict appearance gating.
  A comparative overload probe rejected more valid transition frames with that
  gate enabled. Learned long-term/ReID association remains PXE-0161.

## Files

- Runtime: `src/classes/video_handler.py`, `src/classes/flow_controller.py`,
  `src/classes/fastapi_handler.py`, `src/classes/api_legacy_media_routes.py`
- Dashboard: `VideoStream`, `TrackerSelector`, `TrackerIcon`,
  `DocumentationLink`, `ModelQuickControl`, and `FollowerQuickControl`
- Contracts: `configs/tracker_schemas.yaml`, focused backend/frontend tests,
  tracker and streaming references

## Validation

```text
Focused streaming/video/flow/DaSiamRPN: 117 passed
Phase 0 API inventory/Parameters reload: 73 passed
Docs/tracker/schema contracts:           95 passed
Dashboard:                              404 passed
Generated schema:                        42 sections / 604 parameters, current
Python compile:                          passed
Dashboard production build:              passed
Git whitespace check:                    passed
Public runtime:                           healthy, commit f33ffdeb
Public authenticated WebRTC:              decoded 640x480, readyState 4
Public negotiated WebSocket JPEG:         decoded 640x480, frame age 20.2 ms
Browser page errors:                       none
```

The public evidence used manual run
`pixeagle_manual_7e4592b3-128f-42f6-8267-65abb354b05a`. Process-local video
health remained fresh and reported 32 intentional real-time replay skips after
four file loops. That count proves the catch-up path was active; it is not a
tracker throughput benchmark or remote operator-acceptance result.

## Remaining Evidence

- operator visual tracking continuity on the refreshed public browser demo;
- Raspberry Pi/Jetson/Ubuntu actual-camera full-loop cadence;
- annotated identity-switch, false-lock, recovery, and IoU comparisons.

No PX4, SITL, HIL, service installation, field, real-aircraft, or
military-grade result is claimed.
