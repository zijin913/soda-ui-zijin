#!/usr/bin/env python3
"""
Replay Manager for RRD files.
Handles loading and playback of recorded robot data.
"""

import rerun as rr
import duckdb
import numpy as np
import cv2
from typing import Optional, Dict, List, Tuple
import time


class ReplayManager:
    def __init__(self, rrd_path: str):
        """
        Initialize the replay manager with an RRD file.

        Args:
            rrd_path: Path to the .rrd recording file
        """
        self.rrd_path = rrd_path
        self.recording = None
        self.view = None
        self.current_frame_idx = 0
        self.frames = []
        self.total_frames = 0
        self.is_playing = False
        self.playback_speed = 1.0

        self._load_recording()

    def _load_recording(self):
        """Load the RRD file and extract all frames."""
        print(f"[ReplayManager] Loading recording from: {self.rrd_path}")

        try:
            self.recording = rr.dataframe.load_recording(self.rrd_path)
            self.view = self.recording.view(index="timestamp", contents="/**")

            # Query all data and organize by timestamp
            query = """
                SELECT 
                    timestamp,
                    entity_path,
                    data
                FROM view
                ORDER BY timestamp
            """
            df = duckdb.query(query).df()

            if df.empty:
                raise ValueError("No data found in recording")

            # Group data by timestamp to create frames
            self._organize_frames(df)

            print(f"[ReplayManager] Loaded {self.total_frames} frames")

        except Exception as e:
            print(f"[ReplayManager] Failed to load recording: {e}")
            raise

    def _organize_frames(self, df):
        """Organize data from dataframe into frames."""
        # Group by unique timestamps
        grouped = df.groupby("timestamp")

        for timestamp, group in grouped:
            frame_data = {
                "timestamp": timestamp,
                "video": None,
                "pointcloud": None,
                "joints": {},
            }

            # Extract data by entity path
            for _, row in group.iterrows():
                entity_path = row["entity_path"]
                data = row["data"]

                if entity_path.startswith("camera/rgb"):
                    # Handle video frame
                    if data is not None and len(data) > 0:
                        # Rerun stores images as arrays, need to decode
                        frame_data["video"] = self._decode_image(data)

                elif entity_path.startswith("pointcloud"):
                    # Handle pointcloud
                    if data is not None and len(data) > 0:
                        frame_data["pointcloud"] = data

                elif entity_path.startswith("joints/"):
                    # Handle joint data - format: joints/{joint_name}/{type}
                    parts = entity_path.split("/")
                    if len(parts) >= 3:
                        joint_name = parts[1]
                        joint_type = parts[2]  # angle, velocity, or torque

                        if joint_name not in frame_data["joints"]:
                            frame_data["joints"][joint_name] = {}

                        # Store the joint data by type
                        frame_data["joints"][joint_name][joint_type] = data

            self.frames.append(frame_data)

        self.total_frames = len(self.frames)

    def _decode_image(self, image_data):
        """Decode image data from Rerun format."""
        try:
            if isinstance(image_data, np.ndarray):
                # Check if it's already an image or needs decoding
                if image_data.dtype == np.uint8:
                    if len(image_data.shape) == 3 and image_data.shape[2] == 3:
                        # BGR format (OpenCV)
                        return image_data
                    elif len(image_data.shape) == 3 and image_data.shape[2] == 4:
                        # BGRA format
                        return image_data[:, :, :3]
                return None
            return None
        except Exception as e:
            print(f"[ReplayManager] Failed to decode image: {e}")
            return None

    def get_current_frame(self) -> Optional[Dict]:
        """Get the current frame data."""
        if self.current_frame_idx >= self.total_frames:
            return None

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
        # Find closest frame
        for i, frame in enumerate(self.frames):
            if frame["timestamp"] >= timestamp:
                self.current_frame_idx = i
                return frame

        # Return last frame if timestamp exceeds all
        if self.frames:
            self.current_frame_idx = self.total_frames - 1
            return self.frames[-1]

        return None

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

    def get_frame_at(self, frame_idx: int) -> Optional[Dict]:
        """Get frame at specific index without changing current position."""
        if 0 <= frame_idx < self.total_frames:
            return self.frames[frame_idx]
        return None
