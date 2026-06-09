#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
ConfigManager - Unified Configuration Management
"""

import json
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    """
    Unified configuration manager for SODA OS.

    Consolidates configuration from multiple sources:
    - System defaults
    - YAML/JSON config files
    - Runtime overrides

    Example:
        config = ConfigManager()
        config.load("robot", "configs/robot.yaml")
        config.load("camera", "configs/camera.yaml")

        robot_ip = config.get("robot.network.ip", "127.0.0.1")
        config.set("robot.control.rate", 500)
    """

    # Default configurations
    DEFAULTS = {
        "robot": {
            "type": "firefly_y6",
            "urdf": "firefly_y6_gr100",  # 6-DOF arm with GR100 mass lumped (no separate gripper joints)
            "home_position": [0.0, -0.75, 2.3, 0.9, 0.0, 0.0],  # 6 arm joints (kept in sync with teleop_quest.py HOME_JOINTS)
            "network": {
                "ip": "127.0.0.1",
                "port": 12345,
            },
            "control": {
                "rate": 500,  # Hz (default for real, sim apps can override)
                "position_limits": True,
                "velocity_limits": True,
            },
        },
        "camera": {
            "type": "realsense",
            "network": {
                "ip": "127.0.0.1",
                "port": 12346,
            },
            "resolution": {
                "width": 1920,
                "height": 1080,
            },
            "depth": {
                "enabled": True,
                "min_distance": 0.1,
                "max_distance": 2.0,
            },
        },
        "calibration": {
            "file": None,  # Path to calibration JSON (explicit override)
            "auto_discover": True,  # Auto-search for latest calibration file
            "search_paths": [
                "hand_eye_calibration/results/",
                "config/",
            ],
            "aruco": {
                "dictionary": "DICT_4X4_50",
                "marker_size": 0.04,  # meters
                "board_rows": 4,
                "board_cols": 4,
            },
        },
        "motion": {
            "trajectory": {
                "type": "minimum_jerk",
                "duration": 2.0,  # seconds
            },
            "ik": {
                "max_iterations": 200,
                "tolerance": 1e-4,
                "damping": 0.1,
            },
            "safety": {
                "max_velocity": 1.0,  # rad/s
                "max_acceleration": 2.0,  # rad/s^2
                "workspace_limits": {
                    "x": [-0.5, 0.5],
                    "y": [-0.5, 0.5],
                    "z": [0.0, 0.6],
                },
            },
        },
    }

    def __init__(self, base_path: Optional[Path] = None):
        """
        Initialize ConfigManager.

        Args:
            base_path: Base path for resolving relative config file paths.
                       Defaults to soda workspace root.
        """
        if base_path is None:
            # Default to soda workspace root
            base_path = Path(__file__).parent.parent.parent
        self.base_path = Path(base_path)

        # Start with defaults
        self._config: Dict[str, Any] = {}
        self._deep_update(self._config, self.DEFAULTS)

    def load(self, namespace: str, config_path: str) -> None:
        """
        Load configuration from file into a namespace.

        Args:
            namespace: Config namespace (e.g., "robot", "camera")
            config_path: Path to YAML or JSON config file
        """
        path = self.base_path / config_path
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            if path.suffix in (".yaml", ".yml"):
                data = yaml.safe_load(f)
            elif path.suffix == ".json":
                data = json.load(f)
            else:
                raise ValueError(f"Unsupported config format: {path.suffix}")

        if namespace in self._config:
            self._deep_update(self._config[namespace], data)
        else:
            self._config[namespace] = data

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.

        Args:
            key: Dot-separated key path (e.g., "robot.network.port")
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        parts = key.split(".")
        value = self._config

        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value using dot notation.

        Args:
            key: Dot-separated key path (e.g., "robot.control.rate")
            value: Value to set
        """
        parts = key.split(".")
        config = self._config

        for part in parts[:-1]:
            if part not in config:
                config[part] = {}
            config = config[part]

        config[parts[-1]] = value

    def get_namespace(self, namespace: str) -> Dict[str, Any]:
        """
        Get entire configuration namespace.

        Args:
            namespace: Config namespace (e.g., "robot")

        Returns:
            Configuration dictionary for namespace
        """
        return self._config.get(namespace, {})

    def to_dict(self) -> Dict[str, Any]:
        """Return complete configuration as dictionary."""
        return self._config.copy()

    def save(self, config_path: str, namespace: Optional[str] = None) -> None:
        """
        Save configuration to file.

        Args:
            config_path: Output path (YAML or JSON based on extension)
            namespace: Optional namespace to save (None = save all)
        """
        path = self.base_path / config_path
        path.parent.mkdir(parents=True, exist_ok=True)

        data = self._config.get(namespace, self._config) if namespace else self._config

        with open(path, "w", encoding="utf-8") as f:
            if path.suffix in (".yaml", ".yml"):
                yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
            else:
                json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _deep_update(base: dict, update: dict) -> dict:
        """Recursively update nested dictionary."""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigManager._deep_update(base[key], value)
            else:
                base[key] = value
        return base

    def find_calibration_file(self, arm: Optional[str] = None) -> Optional[str]:
        """
        Find calibration file using configured strategy.

        Priority:
        1. Explicit file path in calibration.file
        2. Auto-discover latest file in search_paths

        If ``arm`` is provided, the search is scoped to per-arm sub-dirs
        (e.g. ``results/left/``) and the JSON is filtered by its ``arm``
        field where present. Falls back to flat search if no per-arm
        candidate is found.

        Returns:
            Path to calibration file or None
        """
        # Check explicit path first (per-arm or top-level key).
        explicit_file = None
        if arm:
            explicit_file = self.get(f"calibration.files.{arm}")
        if not explicit_file:
            explicit_file = self.get("calibration.file")
        if explicit_file:
            path = self.base_path / explicit_file
            if path.exists():
                return str(path)
            print(f"Warning: Calibration file not found: {explicit_file}")

        # Canonical pipeline lays results out as
        # hand_eye_calibration/results/dual/{left_hand,right_hand,side}.json.
        # Try those first so the new EVA-adapted pipeline picks them up
        # without any user config changes.
        if arm in ("left", "right", "side"):
            dual_name = {
                "left":  "left_hand.json",
                "right": "right_hand.json",
                "side":  "side.json",
            }[arm]
            for search_path in self.get("calibration.search_paths", []):
                candidate = self.base_path / search_path / "dual" / dual_name
                if candidate.exists():
                    return str(candidate)

        # Auto-discover if enabled
        if not self.get("calibration.auto_discover", True):
            return None

        search_paths = self.get("calibration.search_paths", [])
        candidate_dirs = []
        for search_path in search_paths:
            search_dir = self.base_path / search_path
            if not search_dir.exists():
                continue
            # When asking for a specific arm, look under results/<arm>/
            # first; fall back to the flat dir for legacy layouts.
            if arm:
                arm_dir = search_dir / arm
                if arm_dir.exists():
                    candidate_dirs.append(arm_dir)
            candidate_dirs.append(search_dir)

        calibration_files: list = []
        for d in candidate_dirs:
            for f in d.glob("*.json"):
                if "calibration" in f.name or "joint_optimized" in f.name:
                    calibration_files.append(f)
            # If we got hits in a per-arm dir, prefer those over the flat
            # search results — most-specific wins.
            if calibration_files and arm and d.name == arm:
                break

        if arm:
            # When the JSON tags itself with an arm field, only keep
            # matching ones. Files without the tag are kept (legacy).
            filtered = []
            for f in calibration_files:
                try:
                    import json
                    with open(f) as fh:
                        data = json.load(fh)
                    if data.get("arm") in (None, arm):
                        filtered.append(f)
                except Exception:
                    filtered.append(f)
            calibration_files = filtered

        if not calibration_files:
            return None

        calibration_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        latest = calibration_files[0]
        print(f"[Config] Auto-discovered calibration ({arm or 'any'}): {latest}")
        return str(latest)

    def find_calibration_files(self) -> dict:
        """Per-camera calibration paths — ``{"left": ..., "right": ..., "side": ...}``.

        Convenience wrapper used by the dual-arm shell startup. The
        ``left``/``right`` keys point at hand (wrist) camera JSONs and
        ``side`` points at the third-person camera JSON (``T_cam2base``).
        Each value is ``None`` if no candidate was found.
        """
        return {key: self.find_calibration_file(key) for key in ("left", "right", "side")}
