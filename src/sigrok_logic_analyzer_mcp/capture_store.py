"""Manages captured data so it can be referenced across MCP tool calls.

Stores both in-memory numpy arrays (for fast native export) and .sr file
paths (for protocol decoding via sigrok-cli).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


class CaptureNotFoundError(Exception):
    """Raised when a capture ID doesn't exist in the store."""


@dataclass
class CaptureInfo:
    capture_id: str
    file_path: str
    created_at: float
    description: str = ""
    data: np.ndarray | None = field(default=None, repr=False)
    num_channels: int = 0
    sample_rate: int = 0


class CaptureStore:
    """Manages captured data in a temp directory with in-memory copies.

    Each capture gets a short human-readable ID (cap_001, cap_002, ...) that
    can be referenced from subsequent tool calls (decode, export, etc.).
    """

    def __init__(self, base_dir: str | None = None) -> None:
        if base_dir is None:
            self._base_dir = tempfile.mkdtemp(prefix="sigrok_logic_analyzer_mcp_")
            self._owns_dir = True
        else:
            os.makedirs(base_dir, exist_ok=True)
            self._base_dir = base_dir
            self._owns_dir = False

        self._captures: dict[str, CaptureInfo] = {}
        self._counter = 0

    @property
    def base_dir(self) -> str:
        return self._base_dir

    def new_capture(self, description: str = "") -> tuple[str, str]:
        """Create a new capture slot.

        Returns (capture_id, file_path) where file_path is the .sr file
        path for saving the capture.
        """
        self._counter += 1
        capture_id = f"cap_{self._counter:03d}"
        file_path = os.path.join(self._base_dir, f"{capture_id}.sr")

        self._captures[capture_id] = CaptureInfo(
            capture_id=capture_id,
            file_path=file_path,
            created_at=time.time(),
            description=description,
        )
        return capture_id, file_path

    def store_data(
        self,
        capture_id: str,
        data: np.ndarray,
        num_channels: int,
        sample_rate: int = 0,
    ) -> None:
        """Attach in-memory capture data to an existing capture."""
        info = self.get(capture_id)
        info.data = data
        info.num_channels = num_channels
        info.sample_rate = sample_rate

    def get(self, capture_id: str) -> CaptureInfo:
        """Get capture info by ID. Raises CaptureNotFoundError if not found."""
        if capture_id not in self._captures:
            available = ", ".join(self._captures.keys()) or "(none)"
            raise CaptureNotFoundError(
                f"Capture '{capture_id}' not found. Available captures: {available}"
            )
        return self._captures[capture_id]

    def list_captures(self) -> list[dict]:
        """List all captures with metadata."""
        result = []
        for info in self._captures.values():
            size = 0
            if os.path.exists(info.file_path):
                size = os.path.getsize(info.file_path)
            result.append({
                "id": info.capture_id,
                "file_path": info.file_path,
                "size_bytes": size,
                "created_at": info.created_at,
                "description": info.description,
                "num_channels": info.num_channels,
                "num_samples": len(info.data) if info.data is not None else 0,
            })
        return result

    def cleanup(self) -> None:
        """Remove all temp files and the base directory if we own it."""
        if self._owns_dir and os.path.exists(self._base_dir):
            shutil.rmtree(self._base_dir, ignore_errors=True)
        self._captures.clear()
