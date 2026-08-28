# Phase 5 Checkpoint: Frame Pipeline Baseline

Date: 2026-08-28
Issue: PXE-0165
Status: implementation verified; target-hardware evidence pending

## Scope

Measured the shared capture-to-stream path after the bounded-latency tracker
work. The active process was left running; no service, flight-control, or
operator runtime was restarted.

## Changes

- Made checked-in frame enhancement opt-in. The default remains a 640x480,
  30 FPS capture request, 640x480, 20 FPS output ceiling, JPEG quality 50
  baseline suitable for initial CPU-only companion testing.
- Kept one explicit 8-bit, three-channel BGR contract at the preprocessor
  boundary. Removed the global color-space selector and registered its exact
  retirement so old local settings are backed up and removed by Config Sync.
- Reused the OpenCV CLAHE object until its clip/grid settings change and added
  clear validation for malformed frames and filter settings. The preprocessor
  also honors the global enable flag when used outside the controller.
- Added schema bounds/descriptions, focused tests, and operator tuning guidance.

## Evidence

On the local x86_64 environment using a synthetic 1280x720 BGR frame, 30 steady
state samples measured approximately:

| Path | Mean | P95 sample |
| --- | ---: | ---: |
| Raw | 0.00 ms | 0.00 ms |
| Gaussian blur | 0.92 ms | 1.49 ms |
| Cached CLAHE | 6.85 ms | 9.88 ms |
| Blur plus cached CLAHE | 8.69 ms | 11.46 ms |

These are processing measurements, not tracking accuracy or target-hardware
acceptance. The earlier live runtime measurement showed tracking and source
cadence, not a universal performance guarantee.

## Validation

- `PYTHONPATH=src .venv/bin/pytest -q tests/unit/video/test_frame_preprocessor.py tests/unit/test_generate_schema.py tests/test_config_service.py`: 179 passed
- `.venv/bin/python scripts/generate_schema.py`: 42 sections, 603 parameters
- `bash scripts/check_schema.sh`: passed
- `PYTHONPATH=src .venv/bin/pytest -q tests/unit/video tests/unit/streaming`: 370 passed
- `PYTHONPATH=src .venv/bin/pytest -q tests/unit/core_app/test_app_controller_offboard_safety.py`: 173 passed
- `make phase0-check`: 509 passed
- `make test`: 3,763 passed, 50 skipped, 1 deselected, 1 existing warning
- Final focused rerun after strict validation: 181 passed

## Risks And Next Slice

The active user configuration may intentionally retain the former enhancement
settings; this slice does not silently overwrite operator-owned values. A
reset or explicit settings change is needed to adopt the new baseline. Actual
Raspberry Pi 5, Jetson, camera, AI-detector, and tracker cadence evidence is
still required. Resize/OSD and transport review found no evidence-based need
for a structural rewrite in this slice; future changes should be driven by
measurements on representative target hardware.
