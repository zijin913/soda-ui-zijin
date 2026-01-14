#!/usr/bin/env python3
"""
Replay Manager for LeRobot datasets.
Handles loading and playback of recorded robot data.
"""

import numpy as np
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict
import cv2
from soda_server.data_reader import DataReader


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
    gripper_distance: float = 0.05


@dataclass
class TrajectoryResponse:
    trajectory: List[TrajectoryPoint]

    def to_dict(self):
        return {"trajectory": [asdict(p) for p in self.trajectory]}


class ReplayManager:
    def __init__(self, db_path: str):
        """
        Initialize replay manager with a dataset directory.

        Args:
            db_path: Path to LeRobot dataset directory
        """
        self.db_path = db_path
        self.reader = None
        self.frames = []
        self.total_frames = 0
        self.current_frame_idx = 0
        self.is_playing = False
        self.playback_speed = 1.0

        self._load_recording()

    def _load_recording(self):
        print(f"[ReplayManager] Loading recording from: {self.db_path}")

        try:
            self.reader = DataReader(self.db_path)
            df = self.reader.df
            joint_names = self.reader.get_joint_names()

            # Extract data column-wise to avoid iterrows() which can fail with extension dtypes
            state_data = np.stack(df["observation.state"].values)
            timestamps = df["timestamp"].values

            has_pc = "observation.pointcloud.positions" in df.columns
            pc_col = df["observation.pointcloud.positions"].values if has_pc else [None] * len(df)

            self.frames = []
            for i in range(len(df)):
                # Group joints for internal storage
                joints = {}
                for j_idx, name in enumerate(joint_names):
                    joints[name] = {"angle": float(state_data[i, j_idx])}

                frame = {
                    "index": i,
                    "timestamp": float(timestamps[i]),
                    "joints": joints,
                    "video": None,
                    "pointcloud": None,
                }

                if has_pc and pc_col[i] is not None:
                    frame["pointcloud"] = np.array(pc_col[i]).reshape(-1, 3)

                self.frames.append(frame)

            self.total_frames = len(self.frames)
            print(f"[ReplayManager] Loaded {self.total_frames} frames.")

        except Exception as e:
            print(f"[ReplayManager] Failed to load recording: {e}")
            import traceback

            traceback.print_exc()
            self.frames = []
            self.total_frames = 0

    def get_current_frame(self) -> Optional[Dict]:
        """Get current frame data."""
        if self.total_frames == 0:
            return None
        if self.current_frame_idx >= self.total_frames:
            self.current_frame_idx = self.total_frames - 1
        return self.frames[self.current_frame_idx]

    def next_frame(self) -> Optional[Dict]:
        """Advance to next frame and return it."""
        if self.current_frame_idx < self.total_frames - 1:
            self.current_frame_idx += 1
            return self.frames[self.current_frame_idx]
        return None

    def previous_frame(self) -> Optional[Dict]:
        """Go to previous frame and return it."""
        if self.current_frame_idx > 0:
            self.current_frame_idx -= 1
            return self.frames[self.current_frame_idx]
        return None

    def seek_to_frame(self, frame_idx: int) -> Optional[Dict]:
        """Seek to specific frame index."""
        if 0 <= frame_idx < self.total_frames:
            self.current_frame_idx = frame_idx
            return self.frames[self.current_frame_idx]
        return None

    def seek_to_time(self, timestamp: float) -> Optional[Dict]:
        """Seek to specific timestamp."""
        if not self.frames:
            return None

        import bisect

        timestamps = [f["timestamp"] for f in self.frames]
        idx = bisect.bisect_left(timestamps, timestamp)

        if idx >= self.total_frames:
            idx = self.total_frames - 1
        if idx > 0:
            t1 = timestamps[idx]
            t0 = timestamps[idx - 1]
            if abs(timestamp - t0) < abs(timestamp - t1):
                idx = idx - 1

        self.current_frame_idx = idx
        return self.frames[idx]

    def reset(self):
        """Reset to beginning of recording."""
        self.current_frame_idx = 0

    def get_progress(self) -> float:
        """Get playback progress as percentage (0.0 to 1.0)."""
        if self.total_frames == 0:
            return 0.0
        return self.current_frame_idx / self.total_frames

    def get_current_timestamp(self) -> Optional[float]:
        """Get current frame timestamp."""
        if self.current_frame_idx < self.total_frames:
            return self.frames[self.current_frame_idx]["timestamp"]
        return None

    def get_duration(self) -> float:
        """Get total duration of recording in seconds."""
        if self.total_frames < 2:
            return 0.0
        return self.frames[-1]["timestamp"] - self.frames[0]["timestamp"]

    def get_trajectory(self) -> TrajectoryResponse:
        trajectory_points = []
        joint_names = self.reader.get_joint_names()

        for f in self.frames:
            joint_states = [
                JointState(
                    id=i,
                    name=name,
                    angle=float(f["joints"].get(name, {}).get("angle", 0.0)),
                    velocity=float(f["joints"].get(name, {}).get("velocity", 0.0)),
                    torque=float(f["joints"].get(name, {}).get("torque", 0.0)),
                )
                for i, name in enumerate(joint_names)
            ]

            trajectory_points.append(
                TrajectoryPoint(
                    index=f["index"],
                    timestamp=f["timestamp"],
                    joints=joint_states,
                    gripper_distance=0.05,
                )
            )
        return TrajectoryResponse(trajectory=trajectory_points)

    def get_chunk(self, start_idx: int, length: int) -> List[Dict]:
        """
        Get a chunk of heavy data (video, pointcloud) for a range of frames.
        """
        chunk = []
        end_idx = min(start_idx + length, self.total_frames)

        # Pre-fetch images if needed. LeRobotDataset decodes on index.
        # We'll use the reader to get images for the range.
        # This is more efficient than loading all images in _load_recording.

        # Note: This is a simplified version. Ideally we'd only decode what's requested.
        for i in range(start_idx, end_idx):
            f = self.frames[i]

            # Extract video frame for this index
            video_bytes = None
            try:
                # We can add a method to reader to get a single image to avoid overhead
                # For now, let's assume we might need to optimize this.
                item = self.reader.dataset[i]
                img_tensor = item["observation.images.camera_rgb"]
                img_np = img_tensor.permute(1, 2, 0).numpy()
                if img_np.dtype == np.float32:
                    img_np = (img_np * 255).astype(np.uint8)
                img_bgr = img_np[..., ::-1]

                success, buffer = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if success:
                    video_bytes = buffer.tobytes()
            except Exception as e:
                # Image might not exist or decode failed
                pass

            pc_data = f["pointcloud"].tolist() if f["pointcloud"] is not None else None

            chunk.append({"index": i, "video": video_bytes, "pointcloud": pc_data})
        return chunk
