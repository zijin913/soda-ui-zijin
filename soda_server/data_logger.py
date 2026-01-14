#!/usr/bin/env python3
"""
URDF Logger using LeRobotDataset interface.
Wraps the LeRobotDataset class from the local soda_datasets package.
"""

import os
import sys
import time
import asyncio
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any

# Add parent directory to sys.path to import from soda_datasets
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from urdf_parser_py import urdf as urdf_parser


class DataLogger:
    def __init__(
        self,
        filepath: str,
        entity_path_prefix: str = "",
        db_path: str = "recordings/dataset",
        fps: int = 30,
        num_points: int = 1024,
        img_shape: tuple[int, int] = (480, 640),
        truncate: bool = False,
    ) -> None:
        self.fps = fps
        self.root = Path(db_path)
        self.entity_path_prefix = entity_path_prefix
        self.num_points = num_points
        self.img_shape = img_shape
        self.start_time = None

        # Parse URDF to get joint names
        self.filepath = filepath
        self.urdf = urdf_parser.URDF.from_xml_file(filepath)
        self.joint_names = [j.name for j in self.urdf.joints if j.type in ["revolute", "continuous", "prismatic"]]

        # Define features for LeRobotDataset
        features = {
            "observation.state": {
                "dtype": "float32",
                "shape": (len(self.joint_names),),
                "names": self.joint_names,
            },
            "observation.images.camera_rgb": {
                "dtype": "video",
                "shape": (3, self.img_shape[0], self.img_shape[1]),
                "names": ["channels", "height", "width"],
            },
            "observation.pointcloud.positions": {
                "dtype": "float32",
                "shape": (self.num_points, 3),
                "names": ["points", "coords"],
            },
            "observation.pointcloud.colors": {
                "dtype": "float32",
                "shape": (self.num_points, 3),
                "names": ["points", "channels"],
            },
        }

        repo_id = f"soda/{self.root.name}"

        if truncate and self.root.exists():
            import shutil

            shutil.rmtree(self.root)

        self.dataset = LeRobotDataset.create(
            repo_id=repo_id,
            fps=self.fps,
            features=features,
            root=self.root,
            use_videos=True,
            tolerance_s=0.1,  # Increase tolerance for simulation timestamps
        )

        self.current_frame = self._reset_frame()
        print(f"[DataLogger] Initialized LeRobotDataset at {self.root} with {self.num_points} points")

    def _reset_frame(self):
        return {
            "observation.state": np.zeros(len(self.joint_names), dtype=np.float32),
            "task": "Simulation run",
        }

    def update_joints(self, joint_positions: Dict[str, float], time_seconds: Optional[float] = None) -> None:
        """Update joint states in current frame."""
        state = self.current_frame["observation.state"]
        for i, name in enumerate(self.joint_names):
            if name in joint_positions:
                state[i] = joint_positions[name]

    def log_image(self, entity_path: str, image: np.ndarray, time_seconds: Optional[float] = None):
        """Log image to current frame."""
        key = f"observation.images.{entity_path.replace('/', '_')}"

        if key in self.dataset.features:
            self.current_frame[key] = image

    def log_points(
        self,
        entity_path: str,
        positions: np.ndarray,
        colors: Optional[np.ndarray] = None,
        time_seconds: Optional[float] = None,
    ):
        """Log point cloud to current frame."""
        # Pad or truncate to fixed length
        if len(positions) > self.num_points:
            pos = positions[: self.num_points]
            col = colors[: self.num_points] if colors is not None else None
        else:
            pos = np.pad(
                positions,
                ((0, self.num_points - len(positions)), (0, 0)),
                mode="constant",
            )
            if colors is not None:
                col = np.pad(
                    colors,
                    ((0, self.num_points - len(colors)), (0, 0)),
                    mode="constant",
                )
            else:
                col = None

        self.current_frame["observation.pointcloud.positions"] = pos.astype(np.float32)
        if col is not None:
            self.current_frame["observation.pointcloud.colors"] = col.astype(np.float32)

    def log_scalar(self, entity_path: str, value: float, time_seconds: Optional[float] = None):
        """Log scalar value (currently ignored if not in features)."""
        pass

    async def commit_frame(self):
        """Commit the current frame to the dataset."""
        # Ensure all required features are present
        for key in self.dataset.features:
            if key not in self.current_frame and key not in [
                "index",
                "frame_index",
                "episode_index",
                "task_index",
                "timestamp",
            ]:
                shape = self.dataset.features[key]["shape"]
                dtype = self.dataset.features[key]["dtype"]
                if dtype == "binary":
                    self.current_frame[key] = b""
                elif dtype in ["image", "video"]:
                    h, w = shape[1], shape[2]
                    self.current_frame[key] = np.zeros((h, w, 3), dtype=np.uint8)
                else:
                    self.current_frame[key] = np.zeros(shape, dtype=dtype)

        self.dataset.add_frame(self.current_frame)
        self.current_frame = self._reset_frame()

    def close(self):
        """Finalize the dataset."""
        self.dataset.save_episode()
        self.dataset.finalize()
        print(f"[DataLogger] Dataset finalized at {self.root}")

    # Async helpers for compatibility with main.py calls
    async def update_joints_async(self, joint_positions, time_seconds=None):
        self.update_joints(joint_positions, time_seconds)

    async def log_image_async(self, entity_path, image, time_seconds=None):
        self.log_image(entity_path, image, time_seconds)

    async def log_points_async(self, entity_path, positions, colors=None, time_seconds=None):
        self.log_points(entity_path, positions, colors, time_seconds)

    async def log_scalar_async(self, entity_path, value, time_seconds=None):
        self.log_scalar(entity_path, value, time_seconds)


def main():
    urdf_file = "public/l6y_gp100/l6y_gp100.urdf"
    if not os.path.exists(urdf_file):
        print("URDF file not found.")
        return

    logger = DataLogger(urdf_file, db_path="test_lerobot_official", num_points=100, truncate=True)

    print("Logging 10 frames...")
    for i in range(10):
        current_time = time.time()

        # Joints
        joint_angles = {name: 0.1 * i for name in logger.joint_names}
        logger.update_joints(joint_angles, time_seconds=current_time)

        # Image
        dummy_img = np.zeros((480, 640, 3), dtype=np.uint8)
        dummy_img[i * 10 : i * 10 + 50, i * 10 : i * 10 + 50] = (0, 255, 0)
        logger.log_image("camera/rgb", dummy_img)

        # Points
        dummy_points = np.random.rand(50, 3).astype(np.float32)
        dummy_colors = np.random.rand(50, 3).astype(np.float32)
        logger.log_points("pointcloud", dummy_points, dummy_colors)

        # Commit
        asyncio.run(logger.commit_frame())
        time.sleep(0.03)

    logger.close()


if __name__ == "__main__":
    main()
