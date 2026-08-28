"""Contract tests for the optional shared frame preprocessor."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
import yaml

from classes.frame_preprocessor import FramePreprocessor
from classes.parameters import Parameters


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _frame() -> np.ndarray:
    return np.random.default_rng(1204).integers(
        0, 256, (96, 128, 3), dtype=np.uint8
    )


def _patch_parameters(**overrides):
    values = {
        "ENABLE_PREPROCESSING": True,
        "PREPROCESSING_USE_BLUR": False,
        "PREPROCESSING_USE_MEDIAN_BLUR": False,
        "PREPROCESSING_USE_CLAHE": False,
        "PREPROCESSING_BLUR_KERNEL_SIZE": 5,
        "PREPROCESSING_MEDIAN_BLUR_KERNEL_SIZE": 5,
        "PREPROCESSING_CLAHE_CLIP_LIMIT": 2.0,
        "PREPROCESSING_CLAHE_TILE_GRID_SIZE": 8,
    }
    values.update(overrides)
    return patch.multiple(Parameters, **values)


@pytest.mark.unit
def test_checked_in_defaults_keep_preprocessing_opt_in_and_bgr_only():
    defaults = yaml.safe_load(
        (PROJECT_ROOT / "configs/config_default.yaml").read_text(encoding="utf-8")
    )["FramePreprocessor"]

    assert defaults["ENABLE_PREPROCESSING"] is False
    assert defaults["PREPROCESSING_USE_BLUR"] is False
    assert defaults["PREPROCESSING_USE_MEDIAN_BLUR"] is False
    assert defaults["PREPROCESSING_USE_CLAHE"] is False
    assert "PREPROCESSING_COLOR_SPACE" not in defaults


@pytest.mark.unit
def test_disabled_preprocessor_returns_an_unchanged_bgr_frame():
    frame = _frame()
    with _patch_parameters(
        ENABLE_PREPROCESSING=False,
        PREPROCESSING_USE_CLAHE=True,
    ), patch.object(cv2, "createCLAHE") as create_clahe:
        result = FramePreprocessor().preprocess(frame)

    assert result is frame
    assert result.dtype == np.uint8
    assert result.shape == frame.shape
    create_clahe.assert_not_called()


@pytest.mark.unit
def test_clahe_state_is_reused_until_settings_change():
    clahe = MagicMock()
    clahe.apply.side_effect = lambda channel: channel
    frame = _frame()

    with _patch_parameters(PREPROCESSING_USE_CLAHE=True), patch.object(
        cv2, "createCLAHE", return_value=clahe
    ) as create_clahe:
        preprocessor = FramePreprocessor()
        first = preprocessor.preprocess(frame)
        second = preprocessor.preprocess(frame)

        assert first.shape == frame.shape
        assert second.shape == frame.shape
        assert create_clahe.call_count == 1

        Parameters.PREPROCESSING_CLAHE_CLIP_LIMIT = 3.0
        preprocessor.preprocess(frame)

    assert create_clahe.call_count == 2


@pytest.mark.unit
def test_preprocessing_rejects_non_bgr_input():
    with _patch_parameters():
        with pytest.raises(ValueError, match="three-channel BGR"):
            FramePreprocessor().preprocess(np.zeros((96, 128), dtype=np.uint8))


@pytest.mark.unit
def test_enabled_enhancements_keep_the_bgr_contract():
    with _patch_parameters(
        PREPROCESSING_USE_BLUR=True,
        PREPROCESSING_USE_CLAHE=True,
    ):
        result = FramePreprocessor().preprocess(_frame())

    assert result.dtype == np.uint8
    assert result.ndim == 3
    assert result.shape[2] == 3


@pytest.mark.unit
def test_invalid_kernel_is_reported_before_opencv_call():
    with _patch_parameters(PREPROCESSING_USE_BLUR=True, PREPROCESSING_BLUR_KERNEL_SIZE=4):
        with pytest.raises(ValueError, match="odd integer"):
            FramePreprocessor().preprocess(_frame())


@pytest.mark.unit
def test_non_integral_filter_settings_are_rejected_without_coercion():
    with _patch_parameters(
        PREPROCESSING_USE_BLUR=True,
        PREPROCESSING_BLUR_KERNEL_SIZE=5.5,
    ):
        with pytest.raises(ValueError, match="odd integer"):
            FramePreprocessor().preprocess(_frame())


@pytest.mark.unit
def test_non_finite_clahe_settings_are_rejected():
    with _patch_parameters(
        PREPROCESSING_USE_CLAHE=True,
        PREPROCESSING_CLAHE_CLIP_LIMIT=float("nan"),
    ):
        with pytest.raises(ValueError, match="greater than zero"):
            FramePreprocessor().preprocess(_frame())
