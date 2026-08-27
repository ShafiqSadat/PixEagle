#!/usr/bin/env python3
"""Run a repeatable short-term tracker benchmark on one local video.

This runner intentionally excludes AppController recovery. It measures the
selected tracker's frame-to-frame measurement behavior from one initial box.
Optional annotations add IoU, center-error, and false-lock evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

import cv2
import numpy as np
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from classes.parameters import Parameters  # noqa: E402
from classes.trackers.tracker_factory import create_tracker  # noqa: E402


BBox = Tuple[int, int, int, int]


def parse_bbox(value: str) -> BBox:
    """Parse x,y,width,height with positive dimensions."""
    try:
        values = tuple(int(component.strip()) for component in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "bbox must contain four integers: x,y,width,height"
        ) from exc
    if len(values) != 4 or values[2] <= 1 or values[3] <= 1:
        raise argparse.ArgumentTypeError(
            "bbox must contain x,y,width,height with width and height above 1"
        )
    return values


def bbox_iou(first: Sequence[float], second: Sequence[float]) -> float:
    """Return axis-aligned intersection over union."""
    ax, ay, aw, ah = (float(value) for value in first)
    bx, by, bw, bh = (float(value) for value in second)
    if min(aw, ah, bw, bh) <= 0.0:
        return 0.0
    intersection_width = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    intersection_height = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    intersection = intersection_width * intersection_height
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0.0 else 0.0


def center_error(first: Sequence[float], second: Sequence[float]) -> float:
    """Return Euclidean center error in pixels."""
    first_center = np.asarray(
        (float(first[0]) + float(first[2]) / 2.0,
         float(first[1]) + float(first[3]) / 2.0)
    )
    second_center = np.asarray(
        (float(second[0]) + float(second[2]) / 2.0,
         float(second[1]) + float(second[3]) / 2.0)
    )
    return float(np.linalg.norm(first_center - second_center))


def load_annotations(path: Optional[Path]) -> Dict[int, Dict[str, Any]]:
    """Load a closed JSON annotation list keyed by zero-based frame number."""
    if path is None:
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    records = loaded.get("frames") if isinstance(loaded, dict) else loaded
    if not isinstance(records, list):
        raise ValueError("annotation JSON must be a list or an object with frames")

    annotations: Dict[int, Dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or "frame" not in record:
            raise ValueError("each annotation requires an integer frame")
        frame_index = int(record["frame"])
        if frame_index < 0 or frame_index in annotations:
            raise ValueError("annotation frame values must be unique and non-negative")
        visible = bool(record.get("visible", True))
        bbox = record.get("bbox")
        if visible:
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise ValueError("visible annotations require bbox [x,y,width,height]")
            parsed_bbox = tuple(float(value) for value in bbox)
            if parsed_bbox[2] <= 0.0 or parsed_bbox[3] <= 0.0:
                raise ValueError("annotation bbox dimensions must be positive")
            bbox = parsed_bbox
        elif bbox is not None:
            raise ValueError("invisible annotations must omit bbox or set it to null")
        annotations[frame_index] = {"visible": visible, "bbox": bbox}
    return annotations


def _percentile(values: Sequence[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), percentile))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_tracker_config(tracker_name: str) -> str:
    section = {
        "SparseFlow": "SparseFlow_Tracker",
        "VitTrack": "VitTrack_Tracker",
    }.get(tracker_name)
    if section is None or hasattr(Parameters, section):
        return "runtime_config"
    defaults = yaml.safe_load(
        (PROJECT_ROOT / "configs/config_default.yaml").read_text(encoding="utf-8")
    )
    setattr(Parameters, section, defaults[section])
    return "checked_in_defaults"


def _accuracy_summary(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    records = list(records)
    visible = [record for record in records if record["visible"]]
    invisible = [record for record in records if not record["visible"]]
    ious = [record["iou"] for record in visible if record["iou"] is not None]
    errors = [
        record["center_error_px"]
        for record in visible
        if record["center_error_px"] is not None
    ]
    false_locks = sum(bool(record["measurement_usable"]) for record in invisible)
    return {
        "annotated_frames": len(records),
        "visible_frames": len(visible),
        "invisible_frames": len(invisible),
        "mean_iou": statistics.fmean(ious) if ious else None,
        "median_center_error_px": statistics.median(errors) if errors else None,
        "precision_at_20px": (
            sum(error <= 20.0 for error in errors) / len(errors) if errors else None
        ),
        "false_lock_count": false_locks,
        "false_lock_rate": false_locks / len(invisible) if invisible else None,
    }


def run(args: argparse.Namespace) -> Dict[str, Any]:
    video_path = args.video.resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")
    annotations = load_annotations(args.annotations)
    config_source = _ensure_tracker_config(args.tracker)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open video: {video_path}")
    reported_fps = float(capture.get(cv2.CAP_PROP_FPS))
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, args.start_frame)
        success, frame = capture.read()
        if not success or frame is None:
            raise RuntimeError(f"could not read start frame {args.start_frame}")

        height, width = frame.shape[:2]
        controller = SimpleNamespace(estimator=None, smart_tracker=None)
        video_handler = SimpleNamespace(width=width, height=height)
        tracker = create_tracker(
            args.tracker,
            video_handler,
            detector=None,
            app_controller=controller,
        )
        tracker.start_tracking(frame, args.bbox)

        frame_index = args.start_frame
        latencies_ms = []
        measurement_count = 0
        failure_count = 0
        first_failure_frame = None
        accuracy_records = []
        processed = 0
        while args.max_frames is None or processed < args.max_frames:
            success, frame = capture.read()
            if not success or frame is None:
                break
            frame_index += 1
            started = time.perf_counter()
            update_success, bbox = tracker.update(frame)
            latencies_ms.append((time.perf_counter() - started) * 1000.0)
            output = tracker.get_output()
            measurement_usable = bool(
                update_success and output.raw_data.get("usable_for_following", False)
            )
            if measurement_usable:
                measurement_count += 1
            else:
                failure_count += 1
                if first_failure_frame is None:
                    first_failure_frame = frame_index

            annotation = annotations.get(frame_index)
            if annotation is not None:
                predicted_bbox = bbox if measurement_usable else None
                truth_bbox = annotation["bbox"]
                accuracy_records.append(
                    {
                        "frame": frame_index,
                        "visible": annotation["visible"],
                        "measurement_usable": measurement_usable,
                        "iou": (
                            bbox_iou(predicted_bbox, truth_bbox)
                            if predicted_bbox is not None and truth_bbox is not None
                            else 0.0 if annotation["visible"] else None
                        ),
                        "center_error_px": (
                            center_error(predicted_bbox, truth_bbox)
                            if predicted_bbox is not None and truth_bbox is not None
                            else None
                        ),
                    }
                )
            processed += 1
    finally:
        capture.release()

    total = measurement_count + failure_count
    tracker_config = (
        asdict(tracker.config)
        if args.tracker == "SparseFlow" and hasattr(tracker, "config")
        else None
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "short_term_measurement_provider_only",
        "tracker": args.tracker,
        "tracker_config_source": config_source,
        "tracker_config": tracker_config,
        "video": {
            "path": str(video_path),
            "sha256": _file_sha256(video_path),
            "width": width,
            "height": height,
            "reported_fps": reported_fps,
            "start_frame": args.start_frame,
            "initial_bbox": list(args.bbox),
            "processed_frames": total,
        },
        "measurement": {
            "usable_frames": measurement_count,
            "failed_frames": failure_count,
            "usable_rate": measurement_count / total if total else None,
            "first_failure_frame": first_failure_frame,
        },
        "latency_ms": {
            "p50": _percentile(latencies_ms, 50.0),
            "p95": _percentile(latencies_ms, 95.0),
            "maximum": max(latencies_ms) if latencies_ms else None,
        },
        "accuracy": _accuracy_summary(accuracy_records) if annotations else None,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "opencv": cv2.__version__,
        },
        "limitations": [
            "AppController prediction and detector-assisted recovery are excluded",
            "No field, flight, or identity-continuity claim follows from this report",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument(
        "--tracker",
        choices=("CSRT", "KCF", "SparseFlow", "VitTrack", "dlib"),
        default="SparseFlow",
    )
    parser.add_argument("--bbox", type=parse_bbox, required=True)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.start_frame < 0:
        parser.error("--start-frame must be non-negative")
    if args.max_frames is not None and args.max_frames <= 0:
        parser.error("--max-frames must be positive")
    try:
        report = run(args)
    except Exception as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Report: {args.output}")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
