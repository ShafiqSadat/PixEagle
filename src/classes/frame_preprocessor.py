"""Optional, low-level image preparation shared by visual providers.

The application pipeline has one frame contract: an 8-bit, three-channel BGR
image.  Enhancements may be enabled for a particular camera or environment,
but they must not change that contract or allocate reusable processing state on
every frame.
"""

from __future__ import annotations

import math
from numbers import Integral
from typing import Any, Callable, List, Optional, Tuple

import cv2
import numpy as np

from classes.parameters import Parameters


class FramePreprocessor:
    """Apply explicitly enabled, capture-side image enhancements."""

    def __init__(self) -> None:
        self.techniques: List[Callable[[np.ndarray], np.ndarray]] = []
        self._clahe: Optional[Any] = None
        self._clahe_signature: Optional[Tuple[float, int]] = None

        if not bool(getattr(Parameters, "ENABLE_PREPROCESSING", True)):
            return

        if Parameters.PREPROCESSING_USE_BLUR:
            self.techniques.append(self.apply_blur)

        if Parameters.PREPROCESSING_USE_MEDIAN_BLUR:
            self.techniques.append(self.apply_median_blur)

        if Parameters.PREPROCESSING_USE_CLAHE:
            self.techniques.append(self.apply_clahe)

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Return a processed BGR frame without changing its image contract."""
        self._validate_bgr_frame(frame)
        for technique in self.techniques:
            frame = technique(frame)
            self._validate_bgr_frame(frame)
        return frame

    @staticmethod
    def _validate_bgr_frame(frame: np.ndarray) -> None:
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8:
            raise ValueError("frame preprocessing requires an 8-bit BGR numpy frame")
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame preprocessing requires a three-channel BGR frame")

    @staticmethod
    def _validate_kernel_size(value: Any, setting_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise ValueError(f"{setting_name} must be an odd integer greater than 1")
        kernel_size = int(value)
        if kernel_size < 3 or kernel_size % 2 == 0:
            raise ValueError(f"{setting_name} must be an odd integer greater than 1")
        return kernel_size

    @staticmethod
    def _validate_positive_integer(value: Any, setting_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
            raise ValueError(f"{setting_name} must be a positive integer")
        return int(value)

    def apply_blur(self, frame: np.ndarray) -> np.ndarray:
        """Apply Gaussian noise reduction when explicitly enabled."""
        kernel_size = self._validate_kernel_size(
            Parameters.PREPROCESSING_BLUR_KERNEL_SIZE,
            "PREPROCESSING_BLUR_KERNEL_SIZE",
        )
        return cv2.GaussianBlur(frame, (kernel_size, kernel_size), 0)

    def apply_median_blur(self, frame: np.ndarray) -> np.ndarray:
        """Apply median filtering for salt-and-pepper sensor noise."""
        kernel_size = self._validate_kernel_size(
            Parameters.PREPROCESSING_MEDIAN_BLUR_KERNEL_SIZE,
            "PREPROCESSING_MEDIAN_BLUR_KERNEL_SIZE",
        )
        return cv2.medianBlur(frame, kernel_size)

    def _get_clahe(self) -> Any:
        """Reuse CLAHE state and rebuild it only when its settings change."""
        clip_limit = float(Parameters.PREPROCESSING_CLAHE_CLIP_LIMIT)
        grid_size = self._validate_positive_integer(
            Parameters.PREPROCESSING_CLAHE_TILE_GRID_SIZE,
            "PREPROCESSING_CLAHE_TILE_GRID_SIZE",
        )
        if not math.isfinite(clip_limit) or clip_limit <= 0:
            raise ValueError("PREPROCESSING_CLAHE_CLIP_LIMIT must be greater than zero")

        signature = (clip_limit, grid_size)
        if self._clahe is None or self._clahe_signature != signature:
            self._clahe = cv2.createCLAHE(
                clipLimit=clip_limit,
                tileGridSize=(grid_size, grid_size),
            )
            self._clahe_signature = signature
        return self._clahe

    def apply_clahe(self, frame: np.ndarray) -> np.ndarray:
        """Enhance luminance while returning the required BGR representation."""
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        enhanced_l = self._get_clahe().apply(l_channel)
        merged = cv2.merge((enhanced_l, a_channel, b_channel))
        return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
