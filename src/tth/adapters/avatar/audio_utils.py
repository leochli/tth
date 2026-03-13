# src/tth/adapters/avatar/audio_utils.py
"""Audio processing utilities for avatar adapters."""
from __future__ import annotations

from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy import signal


class AudioResampler:
    """Convert PCM audio between sample rates.

    Primary use: 24kHz (OpenAI Realtime API) → 16kHz (Simli avatar input).
    """

    def __init__(self, source_rate: int = 24000, target_rate: int = 16000):
        self.source_rate = source_rate
        self.target_rate = target_rate
        self._ratio = target_rate / source_rate

    def resample(self, pcm_data: bytes) -> bytes:
        """Resample 16-bit PCM bytes.

        Args:
            pcm_data: Raw 16-bit mono PCM bytes at source_rate

        Returns:
            Raw 16-bit mono PCM bytes at target_rate
        """
        # 1. Convert bytes to int16 array
        samples = np.frombuffer(pcm_data, dtype=np.int16)
        if len(samples) == 0:
            return b""

        # 2. Calculate output length
        output_len = int(len(samples) * self._ratio)

        # 3. Resample using scipy's FFT-based method (high quality)
        resampled = cast(NDArray[np.float64], signal.resample(samples, output_len))

        # 4. Convert back to int16 bytes (clip to avoid overflow)
        resampled_clipped = np.clip(resampled, -32768, 32767).astype(np.int16)
        return resampled_clipped.tobytes()

    def resample_float(self, pcm_data: bytes) -> NDArray[np.float32]:
        """Resample and return as float32 array normalized to [-1, 1].

        Useful for models that expect float audio input.
        """
        samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) == 0:
            return np.array([], dtype=np.float32)

        output_len = int(len(samples) * self._ratio)
        resampled = cast(NDArray[np.float64], signal.resample(samples, output_len))
        return resampled.astype(np.float32)
