"""Contract tests for the offline classic-tracker benchmark."""

import json
from pathlib import Path

import pytest

from tools.benchmark_classic_tracker import (
    bbox_iou,
    center_error,
    load_annotations,
    parse_bbox,
)


def test_bbox_metrics_are_deterministic():
    assert bbox_iou((0, 0, 10, 10), (5, 0, 10, 10)) == pytest.approx(1 / 3)
    assert center_error((0, 0, 10, 10), (3, 4, 10, 10)) == pytest.approx(5.0)


def test_bbox_parser_rejects_invalid_dimensions():
    assert parse_bbox("1,2,30,40") == (1, 2, 30, 40)
    with pytest.raises(Exception, match="width and height"):
        parse_bbox("1,2,0,40")


def test_annotations_require_unique_closed_records(tmp_path: Path):
    valid = tmp_path / "valid.json"
    valid.write_text(
        json.dumps(
            {
                "frames": [
                    {"frame": 3, "bbox": [1, 2, 30, 40]},
                    {"frame": 4, "visible": False, "bbox": None},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_annotations(valid) == {
        3: {"visible": True, "bbox": (1.0, 2.0, 30.0, 40.0)},
        4: {"visible": False, "bbox": None},
    }

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        json.dumps([{"frame": 3, "bbox": [1, 2, 3, 4]}] * 2),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique"):
        load_annotations(duplicate)
