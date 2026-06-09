#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Driver base classes — dual-arm only.

Both `get_states` and `set_cmds` use a dict-of-arms schema keyed by
``"left"`` / ``"right"``. Cameras likewise return per-arm dicts.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import numpy as np


class RobotDriverBase(ABC):
    """Abstract base for dual-arm robot drivers (sim or real)."""

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def get_dofs(self) -> Optional[int]:
        """DOFs per arm (both arms are assumed identical)."""

    @abstractmethod
    def get_limits(self) -> Optional[np.ndarray]:
        """Joint limits per arm — (n_joints, 2) array of [min, max]."""

    @abstractmethod
    def get_states(self, arm: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Snapshot arm state (and optionally scene objects).

        Args:
            arm: when given ("left"/"right"), read ONLY that arm's client and
                return ``{arm: {...}}``. This matters in realtime mode: each
                ZMQ client serves a frame only once per sequence, so reading
                both arms when a caller needs one lets two parallel callers
                steal each other's frame and get ``None``. Per-arm reads keep
                each client's frame for its own consumer. ``None`` reads all
                arms (legacy both-arm snapshot).

        Schema (arm=None)::

            {
                "left":  {"position": ndarray(n,), "velocity": ndarray(n,),
                          "torque":   ndarray(n,), "timestamp": float},
                "right": {"position": ndarray(n,), "velocity": ndarray(n,),
                          "torque":   ndarray(n,), "timestamp": float},
                "obj":   ndarray(...),   # optional
            }
        """

    @abstractmethod
    def set_cmds(self, cmds: Dict[str, np.ndarray]) -> bool:
        """Send per-arm joint+gripper commands.

        Args:
            cmds: ``{"left": ndarray(n,), "right": ndarray(n,)}``.
                  Missing arms are not commanded this tick.
        """

    def reset_cmd_seq(self) -> None:
        """Re-baseline the robot server's command sequence for this driver's
        client(s). The server rejects commands whose sequence is "stale", and
        any client's ``seq_clear`` on connect resets that shared counter — so a
        teleop state-reader connecting can make this (command) client's sends
        get rejected (arm goes unresponsive). Calling this after such an event
        restores command acceptance. Default: no-op (drivers override)."""
        return None


class CameraDriverBase(ABC):
    """Abstract base for dual-arm camera drivers."""

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def get_rgb(self) -> Optional[Dict[str, np.ndarray]]:
        """Per-arm RGB images: ``{"left": (H,W,3), "right": (H,W,3)}``."""

    @abstractmethod
    def get_depth(self) -> Optional[Dict[str, np.ndarray]]:
        """Per-arm depth (meters): ``{"left": (H,W), "right": (H,W)}``."""

    @abstractmethod
    def get_intrinsics(self) -> Optional[Dict[str, np.ndarray]]:
        """Per-arm intrinsics: ``{"left": (3,3), "right": (3,3)}``."""


class DriverFactory:
    """Create dual-arm sim / real drivers.

    Real-hardware path is not migrated to dual-arm yet (see real_driver.py
    TODO); only ``mode="sim"`` is usable in this slice.
    """

    def __init__(self, mode: str = "sim", config: Optional[Dict[str, Any]] = None):
        self.mode = mode
        self.config = config or {}
        self._sim_driver = None  # shared for sim mode (robot + camera one client)

    def create_robot_driver(self) -> RobotDriverBase:
        if self.mode == "sim":
            from .sim_driver import SimDriver
            if self._sim_driver is None:
                self._sim_driver = SimDriver(self.config.get("sim", {}))
            return self._sim_driver
        from .real_driver import RealRobotDriver
        return RealRobotDriver(self.config.get("robot", {}))

    def create_camera_driver(self) -> CameraDriverBase:
        if self.mode == "sim":
            from .sim_driver import SimDriver
            if self._sim_driver is None:
                self._sim_driver = SimDriver(self.config.get("sim", {}))
            return self._sim_driver
        from .real_driver import RealCameraDriver
        return RealCameraDriver(self.config.get("camera", {}))

    def get_shared_driver(self):
        """In sim mode robot and camera share one driver; None for real."""
        if self.mode == "sim":
            return self._sim_driver
        return None
