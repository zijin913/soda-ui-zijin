"""
TrajectoryRecorder — 双臂 teleop 轨迹录制(deferred-encode 版)
================================================================

为了让 teleop 主循环跟手到 0 延迟,录制策略改成:**episode 进行中只在
内存里 append 原始 RGB 帧 (一个 list / 每相机),什么都不计算**;
``save()`` 时再一次性 mux 出每相机一份 ``.mp4``。

代价:内存占用 = ``num_frames * H * W * 3 * num_cameras`` bytes。
1 分钟 30Hz × 3 相机 × 720p ≈ 6 GB,通过 ``record_resolution`` 和
``max_buffer_mb`` 两个参数控制上限。

落盘结构::

    YYYY-MM-DD_HH-MM-SS/
    ├── trajectory.h5        # 见下方 HDF5 schema (soda-zijin 双臂格式)
    ├── info.json            # arms / cameras / fps / resolution / codec / strategy
    ├── instruction.txt
    ├── policy.md            # controller 名称 (markdown)
    └── cameras/
        ├── left_wrist.mp4   # 在 save() 时编码,episode 已结束
        ├── right_wrist.mp4
        └── side.mp4

HDF5 schema 对齐 ``soda-zijin`` 的 ``dual_arm_trajectory_recorder`` (双臂)::

    action/<arm>/cartesian_position           (T, 6)
    action/<arm>/joint_position               (T, num_joints)   # 指令
    action/<arm>/gripper_position             (T,)
    action/<arm>/robot_state/{cartesian_position, joint_positions,
                              joint_velocities, joint_torques, gripper_position}
    action/controller_info/{controller_on, movement_enabled, success, failure}
    observation/<arm>/robot_state/{cartesian_position, joint_positions,
                                   joint_velocities, joint_torques, gripper_position}
    observation/timestamp/control/{step_start, step_end}        # int64 纳秒
    observation/frame_index                   (T,)              # step → mp4 帧号

与 zijin 的差异 (结构对齐, 非 1:1):图像走 ``cameras/<cam>.mp4`` 而非逐帧
JPEG (``image_format`` attr 标记为 ``"mp4"``);关节数组保留 bimanual 的
``num_joints`` (含 gripper 维) 并额外写 ``joint_torques``;``robot_type``
沿用 bimanual 取值。``action/<arm>/robot_state`` 在同步主循环里即等于
``observation/<arm>/robot_state`` 的同一帧快照。单臂 episode 通过传入
``arms=["left"]`` 也走同一套 schema。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import h5py
import numpy as np


# Resolution presets — used to downsample on capture to keep RAM bounded.
# Aspect ratio is preserved: target height comes from the preset, target
# width is computed from the source aspect.
_RESOLUTION_PRESETS = {
    "native": None,      # no resize
    "1080p":  1080,
    "720p":   720,
    "480p":   480,
}


def _resize_to(img: np.ndarray, target_h: Optional[int]) -> np.ndarray:
    """Aspect-preserving resize. ``target_h=None`` = pass through."""
    if target_h is None:
        return img
    h, w = img.shape[:2]
    if h <= target_h:
        return img
    new_w = int(round(w * target_h / h))
    return cv2.resize(img, (new_w, target_h), interpolation=cv2.INTER_AREA)


class TrajectoryRecorder:
    """Per-episode recorder. One instance = one episode = one directory.

    Memory note: this implementation buffers raw RGB frames in Python
    lists for the duration of the episode. teleop main-loop cost per
    ``record_step()`` is one ``list.append(ndarray)`` ≈ 50 µs.

    All mp4 encoding happens inside ``save()`` (typically 30-60 s for a
    1-minute 1080p × 3-cam episode). Call ``save()`` AFTER the teleop
    loop has stopped — it blocks until encoding completes.
    """

    def __init__(
        self,
        output_root: str,
        cameras: Optional[List[str]] = None,
        arms: Optional[List[str]] = None,
        fps: float = 30.0,
        robot_type: str = "firefly_y6_gr100",
        num_joints: int = 7,
        video_codec: str = "mp4v",
        record_resolution: str = "native",
        max_buffer_mb: float = 16000.0,
    ):
        """
        Args:
            record_resolution: 'native' | '1080p' | '720p' | '480p'.
                Frame height target; width auto-scaled to keep aspect.
                Cuts RAM by ~4× per step down (1080→720 ≈ 2× saving).
            max_buffer_mb: when the in-memory frame buffer exceeds this,
                record_step() stops accepting new frames and prints a
                warning. teleop continues but cameras freeze on disk
                until episode save+restart.
        """
        self.output_root = Path(output_root)
        self.cameras = list(cameras) if cameras else ["left_wrist", "right_wrist", "side"]
        self.arms = list(arms) if arms else ["left", "right"]
        self.fps = float(fps)
        self.robot_type = robot_type
        self.num_joints = num_joints
        self.video_codec = video_codec

        if record_resolution not in _RESOLUTION_PRESETS:
            raise ValueError(
                f"record_resolution {record_resolution!r} must be one of "
                f"{list(_RESOLUTION_PRESETS)}"
            )
        self._resize_target_h = _RESOLUTION_PRESETS[record_resolution]
        self.record_resolution = record_resolution
        self.max_buffer_mb = float(max_buffer_mb)

        self.timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.traj_dir = self.output_root / self.timestamp_str
        self.cameras_dir = self.traj_dir / "cameras"

        self._steps: List[dict] = []
        self._controller_name: str = "unknown"

        # In-memory frame buffers — one Python list per camera. Stored
        # frames are the on-disk shape (post-resize), so the recorded
        # mp4 dimensions match the buffered ndarray dimensions exactly.
        self._frames: Dict[str, List[np.ndarray]] = {cam: [] for cam in self.cameras}
        self._frame_shapes: Dict[str, Tuple[int, int]] = {}      # cam -> (W, H)
        self._bytes_buffered: int = 0
        self._buffer_full_warned: bool = False
        self._finalized = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def num_steps(self) -> int:
        return len(self._steps)

    @property
    def buffer_mb(self) -> float:
        return self._bytes_buffered / (1024 * 1024)

    def record_step(
        self,
        observation: dict,
        action: Optional[dict] = None,
        controller_info: Optional[dict] = None,
    ) -> None:
        """Append one synchronized dual-arm step.

        Main-loop cost: one ``list.append(...)`` per camera (~50 µs total)
        plus the per-arm joint/action dict copies (~100 µs). No video
        encoding, no colorspace conversion, no ZMQ — that all moves to
        :meth:`save`.
        """
        if self._finalized:
            raise RuntimeError("Recorder already saved/discarded")
        self.traj_dir.mkdir(parents=True, exist_ok=True)

        step_idx = len(self._steps)
        t = observation.get("timestamp", time.time())

        if controller_info:
            self._controller_name = controller_info.get("name", self._controller_name)

        # ── Buffer images (no cvtColor — done at save time) ──
        images = observation.get("images") or {}
        for cam in self.cameras:
            img = images.get(cam)
            if img is None:
                continue
            if not (img.ndim == 3 and img.shape[2] == 3):
                continue
            # Resize to bound RAM. cv2 returns a new array so we don't
            # alias whatever buffer the camera service handed us.
            img = _resize_to(img, self._resize_target_h)
            if img.dtype != np.uint8:
                img = np.clip(img, 0, 255).astype(np.uint8)

            # Record once-per-camera shape (W, H) for VideoWriter init.
            h, w = img.shape[:2]
            self._frame_shapes.setdefault(cam, (w, h))

            # Enforce memory ceiling
            frame_bytes = img.nbytes
            if (self._bytes_buffered + frame_bytes) > self.max_buffer_mb * 1024 * 1024:
                if not self._buffer_full_warned:
                    print(f"[TrajectoryRecorder] Buffer hit {self.max_buffer_mb:.0f} MB ceiling — "
                          "freezing camera recording (joints still being saved). "
                          "Stop the episode soon.")
                    self._buffer_full_warned = True
                # Skip this and every subsequent camera frame for this episode.
                continue

            self._frames[cam].append(img)
            self._bytes_buffered += frame_bytes

        # ── Per-arm joint / cartesian / gripper ──
        per_arm: Dict[str, Dict[str, Any]] = {}
        action = action or {}
        for arm in self.arms:
            obs_a = observation.get(arm) or {}
            act_a = (action.get(arm) if isinstance(action, dict) else None) or {}
            per_arm[arm] = {
                "obs_joint_positions":   np.asarray(obs_a.get("joint_positions",   np.zeros(self.num_joints)), dtype=np.float64),
                "obs_joint_velocities":  np.asarray(obs_a.get("joint_velocities",  np.zeros(self.num_joints)), dtype=np.float64),
                "obs_joint_torques":     np.asarray(obs_a.get("joint_torques",     np.zeros(self.num_joints)), dtype=np.float64),
                "obs_cartesian":         np.asarray(obs_a.get("cartesian_position", np.zeros(6)), dtype=np.float64),
                "obs_gripper":           float(obs_a.get("gripper_position", 0.0)),
                "act_joint_position":    np.asarray(act_a.get("joint_position",    obs_a.get("joint_positions", np.zeros(self.num_joints))), dtype=np.float64),
                "act_cartesian":         np.asarray(act_a.get("cartesian_position", obs_a.get("cartesian_position", np.zeros(6))), dtype=np.float64),
                "act_gripper":           float(act_a.get("gripper_position", obs_a.get("gripper_position", 0.0))),
            }

        info = controller_info or {}
        step = {
            "timestamp": t,
            "frame_index": step_idx,
            "per_arm": per_arm,
            "controller_on":   bool(info.get("controller_on", True)),
            "movement_enabled": bool(info.get("movement_enabled", True)),
            "success":         bool(info.get("success", False)),
            "failure":         bool(info.get("failure", False)),
        }
        self._steps.append(step)

    def save(
        self,
        instruction: str = "",
        success: bool = False,
        calibration: Optional[dict] = None,
    ) -> str:
        """Encode mp4 files, write HDF5 + metadata. Blocks for ~30-60 s.

        Returns the absolute path to the episode dir, or '' if there
        were no steps to save.
        """
        if self._finalized:
            return str(self.traj_dir)
        if not self._steps:
            print("[TrajectoryRecorder] No steps recorded; nothing to save.")
            self._finalized = True
            return ""

        # ── 1. Write HDF5 (cheap) ──
        self._write_h5(instruction, success)

        # ── 2. Encode video files (slow — but episode is already over) ──
        peak_mb = self.buffer_mb
        encode_stats: Dict[str, dict] = {}
        for cam, frames in self._frames.items():
            if not frames:
                continue
            shape = self._frame_shapes.get(cam)
            if shape is None:
                continue
            w, h = shape
            self.cameras_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.cameras_dir / f"{cam}.mp4"

            print(f"[TrajectoryRecorder] Encoding mp4 {out_path.name} "
                  f"({len(frames)} frames @ {w}x{h}) ...")
            t0 = time.time()
            fourcc = cv2.VideoWriter_fourcc(*self.video_codec)
            writer = cv2.VideoWriter(str(out_path), fourcc, self.fps, (w, h))
            if not writer.isOpened():
                print(f"  ✗ VideoWriter failed to open {out_path}")
                continue
            written = 0
            try:
                for rgb in frames:
                    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                    writer.write(bgr)
                    written += 1
            finally:
                writer.release()
            dt = time.time() - t0
            encode_stats[cam] = {
                "frames":  written,
                "seconds": round(dt, 2),
                "fps":     round(written / dt, 1) if dt > 0 else 0.0,
                "resolution": [w, h],
            }
            print(f"  ✓ {out_path.name} done ({written} frames in {dt:.1f}s)")

            # Drop refs eagerly to let RAM go back as we go.
            self._frames[cam] = []

        # ── 3. Sidecars (info.json, instruction.txt, calibration.json) ──
        self._write_sidecars(instruction, success, calibration,
                             encode_stats=encode_stats, peak_mb=peak_mb)

        self._finalized = True
        T = len(self._steps)
        print(f"[TrajectoryRecorder] Saved {T} steps to {self.traj_dir} "
              f"({'success' if success else 'failure'}, peak {peak_mb:.0f} MB)")
        return str(self.traj_dir)

    def discard(self) -> None:
        """Drop everything in memory + delete the episode directory."""
        if self._finalized:
            return
        for cam in list(self._frames):
            self._frames[cam] = []
        self._bytes_buffered = 0
        import shutil
        if self.traj_dir.exists():
            shutil.rmtree(self.traj_dir)
        self._finalized = True
        print(f"[TrajectoryRecorder] Discarded {self.traj_dir}")

    def __len__(self):
        return len(self._steps)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _stack(self, field: str, arm: str) -> np.ndarray:
        return np.stack([s["per_arm"][arm][field] for s in self._steps])

    def _write_h5(self, instruction: str, success: bool) -> None:
        h5_path = self.traj_dir / "trajectory.h5"
        T = len(self._steps)

        # Control-window timestamps (seconds → int64 nanoseconds). We capture
        # one timestamp per synchronized step, so step_end mirrors the NEXT
        # step's start (last step repeats its own start) to give consumers a
        # sane [start, end) window — matches zijin's step_start/step_end pair.
        step_start = (np.array([s["timestamp"] for s in self._steps],
                               dtype=np.float64) * 1e9).astype(np.int64)
        step_end = step_start.copy()
        if T > 1:
            step_end[:-1] = step_start[1:]

        with h5py.File(h5_path, "w") as f:
            for arm in self.arms:
                # Per-arm observed robot state (reused for action/<arm>/robot_state
                # — synchronous loop means same snapshot at command time).
                obs_jp   = self._stack("obs_joint_positions", arm)
                obs_jv   = self._stack("obs_joint_velocities", arm)
                obs_jt   = self._stack("obs_joint_torques", arm)
                obs_cart = self._stack("obs_cartesian", arm)
                obs_grip = np.array([s["per_arm"][arm]["obs_gripper"] for s in self._steps])

                def _write_robot_state(group: str) -> None:
                    f.create_dataset(f"{group}/cartesian_position", data=obs_cart)
                    f.create_dataset(f"{group}/joint_positions",    data=obs_jp)
                    f.create_dataset(f"{group}/joint_velocities",   data=obs_jv)
                    f.create_dataset(f"{group}/joint_torques",      data=obs_jt)  # bimanual extra
                    f.create_dataset(f"{group}/gripper_position",   data=obs_grip)

                # observation/<arm>/robot_state/*
                _write_robot_state(f"observation/{arm}/robot_state")

                # action/<arm>/* (commanded) + nested robot_state snapshot
                f.create_dataset(f"action/{arm}/cartesian_position",
                                 data=self._stack("act_cartesian", arm))
                f.create_dataset(f"action/{arm}/joint_position",
                                 data=self._stack("act_joint_position", arm))
                f.create_dataset(f"action/{arm}/gripper_position",
                                 data=np.array([s["per_arm"][arm]["act_gripper"] for s in self._steps]))
                _write_robot_state(f"action/{arm}/robot_state")

            # Controller flags live under action/controller_info (zijin dual-arm).
            f.create_dataset("action/controller_info/controller_on",
                             data=np.array([s["controller_on"] for s in self._steps], dtype=bool))
            f.create_dataset("action/controller_info/movement_enabled",
                             data=np.array([s["movement_enabled"] for s in self._steps], dtype=bool))
            f.create_dataset("action/controller_info/success",
                             data=np.array([s["success"] for s in self._steps], dtype=bool))
            f.create_dataset("action/controller_info/failure",
                             data=np.array([s["failure"] for s in self._steps], dtype=bool))

            f.create_dataset("observation/timestamp/control/step_start", data=step_start)
            f.create_dataset("observation/timestamp/control/step_end",   data=step_end)
            # step → mp4 frame map (bimanual extra; images are mp4, not jpg).
            f.create_dataset("observation/frame_index",
                             data=np.array([s["frame_index"] for s in self._steps], dtype=np.int64))

            f.attrs["controller"]       = self._controller_name
            f.attrs["instruction"]      = instruction
            f.attrs["success"]          = success
            f.attrs["failure"]          = not success
            f.attrs["controller_on"]    = True
            f.attrs["movement_enabled"] = True
            f.attrs["t_step"]           = T - 1
            f.attrs["time"]             = self.timestamp_str
            f.attrs["robot_type"]       = self.robot_type
            f.attrs["dual_arm"]         = len(self.arms) > 1
            f.attrs["arms"]             = self.arms
            f.attrs["cameras"]          = self.cameras
            f.attrs["fps"]              = self.fps
            f.attrs["video_codec"]      = self.video_codec
            f.attrs["image_format"]     = "mp4"   # NB: zijin uses per-frame jpg
            f.attrs["version_number"]   = 2.0     # zijin dual-arm schema v2

    def _write_sidecars(
        self,
        instruction: str,
        success: bool,
        calibration: Optional[dict],
        encode_stats: Dict[str, dict],
        peak_mb: float,
    ) -> None:
        (self.traj_dir / "instruction.txt").write_text(instruction)
        # policy.md — controller name as markdown (matches zijin sidecars).
        (self.traj_dir / "policy.md").write_text(
            f"# Controller\n\n{self._controller_name}\n")

        # Resolution: pick whichever camera has a shape recorded
        resolution = None
        for cam in self.cameras:
            if cam in self._frame_shapes:
                resolution = list(self._frame_shapes[cam])
                break

        info = {
            "controller":  self._controller_name,
            "robot_type":  self.robot_type,
            "dual_arm":    len(self.arms) > 1,
            "success":     success,
            "failure":     not success,
            "time":        self.timestamp_str,
            "num_timesteps": len(self._steps),
            "fps":         self.fps,
            "arms":        self.arms,
            "cameras":     self.cameras,
            "image_format": "mp4",
            "schema_version": 2.0,
            "video_codec": self.video_codec,
            "resolution":  resolution,
            "record_resolution": self.record_resolution,
            "recording_strategy": "deferred",
            "peak_buffer_mb": round(peak_mb, 1),
            "buffer_full_warned": self._buffer_full_warned,
            "instruction": instruction,
            "video_files": {cam: f"cameras/{cam}.mp4" for cam in encode_stats},
            "video_frame_counts": {cam: s["frames"] for cam, s in encode_stats.items()},
            "encode_seconds":     {cam: s["seconds"] for cam, s in encode_stats.items()},
        }
        with open(self.traj_dir / "info.json", "w") as f:
            json.dump(info, f, indent=2)

        if calibration:
            with open(self.traj_dir / "calibration.json", "w") as f:
                json.dump(calibration, f, indent=2)
