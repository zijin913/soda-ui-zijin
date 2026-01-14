#!/usr/bin/env python3
"""
Replay Manager for DuckDB files.
Handles loading and playback of recorded robot data.
"""

import numpy as np
from typing import Optional, Dict, List, Any
import time
import cv2
import base64
from rrd_reader import PandasReader


class ReplayManager:
    def __init__(self, db_path: str):
        """
        Initialize replay manager with a DuckDB file.

        Args:
            db_path: Path to .duckdb recording file
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
            self.reader = PandasReader(self.db_path)

            # Temporary dict: rounded_timestamp_str -> frame_data
            # We round to 4 decimal places (0.1ms precision) to group data
            frames_map: Dict[str, Dict[str, Any]] = {}

            def get_frame(t_val):
                # Round to ensure matching
                key = f"{t_val:.4f}"
                if key not in frames_map:
                    frames_map[key] = {"timestamp": t_val, "video": None, "pointcloud": None, "joints": {}}
                return frames_map[key]

            # 1. Load Images
            print("[ReplayManager] Loading images...")
            images = self.reader.get_images("camera/rgb")
            for item in images:
                f = get_frame(item["time"])
                f["video"] = item["image"]

            # 2. Load PointClouds
            print("[ReplayManager] Loading pointclouds...")
            # 假设 entity name 是 pointcloud
            # 如果不确定，可以搜索
            all_entities = self.reader.get_all_entity_paths()
            pc_entity = next((e for e in all_entities if "pointcloud" in e), "pointcloud")

            pcs = self.reader.get_points(pc_entity)
            for item in pcs:
                f = get_frame(item["time"])
                f["pointcloud"] = item["positions"]

            # 3. Load Joints
            print("[ReplayManager] Loading joints...")
            joint_paths = [p for p in all_entities if "joints/" in p]

            for path in joint_paths:
                # expected path: joints/{joint_name}/{property}
                parts = path.split("/")
                # find index of 'joints'
                try:
                    idx = parts.index("joints")
                    if idx + 2 >= len(parts):
                        continue

                    joint_name = parts[idx + 1]
                    prop_name = parts[idx + 2]  # angle, velocity, torque
                except ValueError:
                    continue

                df = self.reader.get_scalar(path)
                if df.empty:
                    continue

                # Iterate rows
                # Using itertuples for speed
                for row in df.itertuples(index=False):
                    # row: time, value
                    t = row.time
                    val = row.value

                    f = get_frame(t)
                    if joint_name not in f["joints"]:
                        f["joints"][joint_name] = {}
                    f["joints"][joint_name][prop_name] = float(val)

            # 4. Convert to list and sort
            print("[ReplayManager] Organizing frames...")
            # Sort by timestamp
            sorted_keys = sorted(frames_map.keys())
            self.frames = [frames_map[k] for k in sorted_keys]
            self.total_frames = len(self.frames)

            print(f"[ReplayManager] Loaded {self.total_frames} frames.")

        except Exception as e:
            print(f"[ReplayManager] Failed to load recording: {e}")
            import traceback

            traceback.print_exc()
            # Don't raise, just empty frames
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

        # Find closest frame
        # Simple linear search or binary search could be better
        # Given frames are sorted by timestamp

        # Binary search (bisect_left logic)
        import bisect

        timestamps = [f["timestamp"] for f in self.frames]
        idx = bisect.bisect_left(timestamps, timestamp)

        if idx >= self.total_frames:
            idx = self.total_frames - 1

        # Check if prev is closer
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

    def get_trajectory(self) -> List[Dict]:
        """
        Get the lightweight trajectory (joints and timestamps) without heavy data.
        Returns a list of dicts suitable for client-side playback.
        """
        trajectory = []
        for i, f in enumerate(self.frames):
            # Convert joint dict to list format expected by frontend
            joint_states = []
            if "joints" in f:
                for joint_name, joint_values in f["joints"].items():
                    joint_states.append(
                        {
                            "name": joint_name,
                            "angle": float(joint_values.get("angle", 0.0)),
                            "velocity": float(joint_values.get("velocity", 0.0)),
                            "torque": float(joint_values.get("torque", 0.0)),
                        }
                    )

            trajectory.append(
                {
                    "index": i,
                    "timestamp": f["timestamp"],
                    "joints": joint_states,
                    "gripper_distance": 0.05,  # Placeholder or real value if recorded
                }
            )
        return trajectory

    def get_chunk(self, start_idx: int, length: int) -> List[Dict]:
        """
        Get a chunk of heavy data (video, pointcloud) for a range of frames.
        Video is returned as JPEG bytes (for MessagePack).
        """
        chunk = []
        end_idx = min(start_idx + length, self.total_frames)

        for i in range(start_idx, end_idx):
            f = self.frames[i]

            # Encode video
            video_bytes = None
            if f.get("video") is not None:
                success, buffer = cv2.imencode(".jpg", f["video"], [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if success:
                    video_bytes = buffer.tobytes()

            # Convert pointcloud
            pc_data = None
            if f.get("pointcloud") is not None:
                pc_data = f["pointcloud"].tolist()

            chunk.append({"index": i, "video": video_bytes, "pointcloud": pc_data})
        return chunk
