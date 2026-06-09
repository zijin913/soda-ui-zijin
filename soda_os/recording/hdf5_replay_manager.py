#!/usr/bin/env python3
"""
Hdf5ReplayManager — replay teleop ``trajectory.h5`` directly
============================================================

The backend's replay playback task / ``/api/replay/*`` endpoints drive the arms
from this reader. It reads the zijin-aligned HDF5 **action** stream written by
``soda_os/data/trajectory_recorder.py``:

    action/<arm>/joint_position   (T, >=6)   joint commands (first 6 dims used)
    action/<arm>/gripper_position (T,)        gripper commands
    observation/timestamp/control/step_start  (T,)  int64 nanoseconds

The recording frame rate is often higher than the ZMQ rate playback can reliably
sustain (teleop can reach 150Hz), so on load it resamples by timestamp to
``target_fps`` (default 30Hz) so the backend playback
task can stream it frame-by-frame in real time. Images are not replayed here
(they live in cameras/*.mp4), and ``get_chunk`` returns empty — this class only
exists to drive the arms.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List

import h5py
import numpy as np

_ARMS = ("left", "right")


@dataclass
class JointState:
    id: int
    name: str
    angle: float
    velocity: float = 0.0
    torque: float = 0.0


@dataclass
class TrajectoryPoint:
    index: int
    timestamp: float
    joints: List[JointState]
    gripper_distance: float = 0.05      # left arm (frontend compat)
    gripper_distance_right: float = 0.05


# Same grip-distance mapping the WS layer uses so playback gripper rendering
# matches realtime. Lifted from soda_os/shell/websockets/legacy.py.
_GRIP_CLOSE_ANGLE = 1.50
_GRIP_MAX_DIST = 0.094
_GRIP_MIN_DIST = 0.000


def _grip_angle_to_distance(angle: float) -> float:
    ratio = max(0.0, min(1.0, angle / _GRIP_CLOSE_ANGLE))
    return _GRIP_MAX_DIST - ratio * (_GRIP_MAX_DIST - _GRIP_MIN_DIST)
_PER_ARM_NAMES = ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5",
                  "joint_6", "gripper"]


def _resolve_h5(path: str) -> Path:
    p = Path(path)
    if p.is_file():
        return p
    if p.is_dir() and (p / "trajectory.h5").is_file():
        return p / "trajectory.h5"
    raise FileNotFoundError(f"trajectory.h5 not found for {path!r}")


class Hdf5ReplayManager:
    """Read-only playback of one teleop ``trajectory.h5`` episode.

    Drives via the recorded ACTION (commanded) joints — same choice as the
    standalone zijin-style replay. ``target_fps`` resamples the (possibly
    high-rate) recording so the backend can stream it in real time.
    """

    def __init__(self, db_path: str, target_fps: float = 30.0) -> None:
        self.root = _resolve_h5(db_path)
        print(f"[Hdf5ReplayManager] Loading {self.root}")

        joints: Dict[str, np.ndarray] = {}
        grippers: Dict[str, np.ndarray] = {}
        with h5py.File(self.root, "r") as f:
            for arm in _ARMS:
                jp = np.asarray(f[f"action/{arm}/joint_position"][:], dtype=np.float64)
                joints[arm] = jp[:, :6]
                grippers[arm] = np.asarray(
                    f[f"action/{arm}/gripper_position"][:], dtype=np.float64)
            ts_ns = np.asarray(
                f["observation/timestamp/control/step_start"][:], dtype=np.int64)
        ts_s = ts_ns / 1e9
        T_raw = len(ts_s)

        # Resample to target_fps by timestamp so playback is real-time.
        t = ts_s - ts_s[0] if T_raw else np.zeros(0)
        dur = float(t[-1]) if T_raw > 1 else 0.0
        if T_raw <= 1 or dur <= 0.0:
            idx_map = np.arange(T_raw, dtype=np.int64)
        else:
            n = max(1, int(round(dur * target_fps)))
            sample_t = np.linspace(0.0, dur, n + 1)
            idx_map = np.clip(np.searchsorted(t, sample_t), 0, T_raw - 1)

        # Build per-frame 7-vec (6 arm joints + gripper) for both arms.
        self._left = np.zeros((len(idx_map), 7), dtype=np.float64)
        self._right = np.zeros((len(idx_map), 7), dtype=np.float64)
        for k, src in enumerate(idx_map):
            self._left[k, :6] = joints["left"][src]
            self._left[k, 6] = grippers["left"][src]
            self._right[k, :6] = joints["right"][src]
            self._right[k, 6] = grippers["right"][src]
        self._ts = ts_s[idx_map] if T_raw else np.zeros(0)

        self.fps = float(target_fps)
        self.total_frames = len(idx_map)
        self.current_frame_idx = 0
        self.is_playing = False
        self.joint_names = [f"{a}_{n}" for a in _ARMS for n in _PER_ARM_NAMES]
        print(f"[Hdf5ReplayManager] {T_raw} raw → {self.total_frames} frames "
              f"@ {self.fps:.0f}Hz ({dur:.1f}s)")

    # ---- joint commands for the playback task ----

    def get_frame_joints(self, idx: int):
        """``(left_q, right_q)`` 7-vec (6 arm + gripper) for frame ``idx``,
        or ``(None, None)`` if out of range."""
        if self.total_frames == 0 or not (0 <= idx < self.total_frames):
            return None, None
        return self._left[idx].copy(), self._right[idx].copy()

    # ---- scrub metadata (UI timeline) ----

    def get_trajectory(self) -> Dict[str, Any]:
        if self.total_frames == 0:
            return {"trajectory": []}
        n_per = len(_PER_ARM_NAMES)
        traj = []
        for i in range(self.total_frames):
            row = np.concatenate([self._left[i], self._right[i]])
            joints = [JointState(id=j, name=self.joint_names[j], angle=float(row[j]))
                      for j in range(len(self.joint_names))]
            traj.append(asdict(TrajectoryPoint(
                index=i,
                timestamp=float(self._ts[i]),
                joints=joints,
                gripper_distance=_grip_angle_to_distance(float(self._left[i, 6])),
                gripper_distance_right=_grip_angle_to_distance(float(self._right[i, 6])),
            )))
        return {"trajectory": traj}

    def get_chunk(self, start_idx: int, length: int) -> List[Dict]:
        # Images live in cameras/*.mp4, not wired for HDF5 UI streaming.
        return []

    # ---- misc ----

    def seek_to_frame(self, frame_idx: int) -> None:
        self.current_frame_idx = max(0, min(self.total_frames - 1, frame_idx))

    def get_progress(self) -> float:
        if self.total_frames == 0:
            return 0.0
        return self.current_frame_idx / self.total_frames

    def get_duration(self) -> float:
        if self.total_frames < 2:
            return 0.0
        return float(self._ts[-1] - self._ts[0])

    def get_current_timestamp(self):
        if self.total_frames == 0:
            return None
        return float(self._ts[self.current_frame_idx])
