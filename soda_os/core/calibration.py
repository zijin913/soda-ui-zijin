#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
CalibrationManager - Hand-Eye Calibration Data Management
=========================================================

Manages loading, saving, and applying calibration data.
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime


class CalibrationManager:
    """
    Manager for hand-eye calibration data.

    Handles:
    - Loading calibration results from JSON files
    - Storing camera intrinsics
    - Managing multiple calibration profiles

    Example:
        calib = CalibrationManager()
        calib.load("results/joint_optimized_1920x1080.json")

        T_cam2gripper = calib.T_cam2gripper
        K = calib.intrinsics
    """

    def __init__(self, calibration_path: Optional[str] = None):
        """
        Initialize calibration manager.

        Args:
            calibration_path: Path to calibration JSON file (optional)
        """
        self._T_cam2gripper: Optional[np.ndarray] = None
        self._T_cam2base: Optional[np.ndarray] = None
        self._intrinsics: Optional[np.ndarray] = None
        self._side_intrinsics: Optional[np.ndarray] = None
        self._metadata: Dict[str, Any] = {}
        self._side_metadata: Dict[str, Any] = {}

        if calibration_path:
            self.load(calibration_path)

    def load(self, path: str) -> None:
        """
        Load calibration from JSON file.

        Expected format:
        {
            "T_cam2gripper": [[...], [...], [...], [...]],
            "intrinsics": {"fx": ..., "fy": ..., "cx": ..., "cy": ...},
            "resolution": {"width": ..., "height": ...},
            "method": "...",
            "timestamp": "...",
            "metrics": {...}
        }

        Args:
            path: Path to calibration JSON file
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Calibration file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Load transform
        if "T_cam2gripper" in data:
            self._T_cam2gripper = np.array(data["T_cam2gripper"])
        elif "transform" in data:
            self._T_cam2gripper = np.array(data["transform"])
        else:
            raise ValueError("Calibration file missing T_cam2gripper or transform")

        # Load intrinsics
        if "intrinsics" in data:
            intr = data["intrinsics"]
            if isinstance(intr, dict):
                self._intrinsics = np.array([
                    [intr["fx"], 0, intr["cx"]],
                    [0, intr["fy"], intr["cy"]],
                    [0, 0, 1]
                ])
            elif isinstance(intr, list):
                self._intrinsics = np.array(intr)

        # Store metadata
        self._metadata = {
            "path": str(path),
            "resolution": data.get("resolution"),
            "method": data.get("method"),
            "timestamp": data.get("timestamp"),
            "metrics": data.get("metrics", {}),
        }

    def save(self, path: str, include_metrics: bool = True) -> None:
        """
        Save calibration to JSON file.

        Args:
            path: Output path
            include_metrics: Include metrics in output
        """
        if self._T_cam2gripper is None:
            raise ValueError("No calibration data to save")

        data = {
            "T_cam2gripper": self._T_cam2gripper.tolist(),
            "timestamp": datetime.now().isoformat(),
        }

        if self._intrinsics is not None:
            data["intrinsics"] = {
                "fx": float(self._intrinsics[0, 0]),
                "fy": float(self._intrinsics[1, 1]),
                "cx": float(self._intrinsics[0, 2]),
                "cy": float(self._intrinsics[1, 2]),
            }

        if self._metadata.get("resolution"):
            data["resolution"] = self._metadata["resolution"]

        if include_metrics and self._metadata.get("metrics"):
            data["metrics"] = self._metadata["metrics"]

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_side_camera(self, path: str) -> None:
        """
        Load side (third-person) camera calibration from JSON.

        Expects ``{"T_cam2base": [[...], [...], [...], [...]], "intrinsics": {...}, ...}``
        — produced by ``hand_eye_calibration/scripts/calibrate_camera.py --camera side``
        or ``advanced/joint_optimization.py --camera-type side``.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Side camera calibration file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "T_cam2base" not in data:
            raise ValueError("Side camera calibration file missing T_cam2base")

        self._T_cam2base = np.array(data["T_cam2base"])

        intr = data.get("intrinsics")
        if isinstance(intr, dict):
            self._side_intrinsics = np.array([
                [intr["fx"], 0,         intr["cx"]],
                [0,          intr["fy"], intr["cy"]],
                [0,          0,          1],
            ])
        elif isinstance(intr, list):
            self._side_intrinsics = np.array(intr)

        self._side_metadata = {
            "path":       str(path),
            "base_frame": data.get("base_frame"),
            "resolution": data.get("resolution"),
            "method":     data.get("method"),
            "timestamp":  data.get("timestamp"),
            "metrics":    data.get("metrics", {}),
        }

    @property
    def T_cam2gripper(self) -> np.ndarray:
        """Get camera-to-gripper transformation matrix."""
        if self._T_cam2gripper is None:
            raise ValueError("No calibration loaded. Call load() first.")
        return self._T_cam2gripper.copy()

    @T_cam2gripper.setter
    def T_cam2gripper(self, value: np.ndarray) -> None:
        """Set camera-to-gripper transformation matrix."""
        self._T_cam2gripper = np.asarray(value)

    @property
    def T_cam2base(self) -> np.ndarray:
        """Side camera-to-base transformation matrix (set via load_side_camera)."""
        if self._T_cam2base is None:
            raise ValueError("No side camera calibration loaded. Call load_side_camera() first.")
        return self._T_cam2base.copy()

    @T_cam2base.setter
    def T_cam2base(self, value: np.ndarray) -> None:
        self._T_cam2base = np.asarray(value)

    @property
    def side_intrinsics(self) -> Optional[np.ndarray]:
        """Side camera intrinsic matrix (3x3)."""
        return self._side_intrinsics.copy() if self._side_intrinsics is not None else None

    @property
    def has_side_camera(self) -> bool:
        return self._T_cam2base is not None

    @property
    def intrinsics(self) -> Optional[np.ndarray]:
        """Get camera intrinsic matrix (3x3)."""
        return self._intrinsics.copy() if self._intrinsics is not None else None

    @intrinsics.setter
    def intrinsics(self, value: np.ndarray) -> None:
        """Set camera intrinsic matrix."""
        self._intrinsics = np.asarray(value)

    def set_intrinsics_from_params(
        self, fx: float, fy: float, cx: float, cy: float
    ) -> None:
        """Set intrinsics from individual parameters."""
        self._intrinsics = np.array([
            [fx, 0, cx],
            [0, fy, cy],
            [0, 0, 1]
        ])

    @property
    def resolution(self) -> Optional[Dict[str, int]]:
        """Get calibration resolution (width, height)."""
        return self._metadata.get("resolution")

    @property
    def metrics(self) -> Dict[str, Any]:
        """Get calibration quality metrics."""
        return self._metadata.get("metrics", {})

    @property
    def is_loaded(self) -> bool:
        """Check if calibration is loaded."""
        return self._T_cam2gripper is not None

    def get_translation(self) -> np.ndarray:
        """Get translation component of T_cam2gripper."""
        return self.T_cam2gripper[:3, 3]

    def get_rotation(self) -> np.ndarray:
        """Get rotation matrix component of T_cam2gripper."""
        return self.T_cam2gripper[:3, :3]

    def __repr__(self) -> str:
        if not self.is_loaded:
            return "CalibrationManager(not loaded)"

        info = f"CalibrationManager(loaded from {self._metadata.get('path', 'unknown')})"
        if self.resolution:
            info += f"\n  Resolution: {self.resolution['width']}x{self.resolution['height']}"
        if self.metrics:
            pos_err = self.metrics.get("mean_position_error_mm")
            if pos_err:
                info += f"\n  Position error: {pos_err:.2f}mm"
        return info
