#!/usr/bin/env python3
"""
Pandas Reader for Soda using LeRobotDataset interface.
"""

import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any
from pathlib import Path

# Add parent directory to sys.path to import from soda_datasets
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from lerobot.datasets.lerobot_dataset import LeRobotDataset


class PandasReader:
    def __init__(self, db_path: str):
        """
        Initialize reader using LeRobotDataset.
        db_path: Path to the dataset directory.
        """
        self.root = Path(db_path)
        if not self.root.is_dir():
            # If it's a file, try the parent
            self.root = self.root.parent

        print(f"[PandasReader] Loading LeRobotDataset from: {self.root}")

        # Load dataset
        # repo_id is not strictly needed for local loading if root is provided
        self.dataset = LeRobotDataset(
            repo_id="local/dataset", root=self.root, tolerance_s=0.1
        )

        # Access hf_dataset for easy filtering
        self.df = self.dataset.hf_dataset.to_pandas()
        print(f"[PandasReader] Loaded {len(self.df)} frames.")

    def get_all_entity_paths(self) -> List[str]:
        """
        Map LeRobot column names back to SODA entity paths.
        """
        entities = set()
        for col in self.df.columns:
            if col.startswith("observation.images."):
                entities.add(col[len("observation.images.") :].replace("_", "/"))
            elif col.startswith("observation.state"):
                # Add individual joints for compatibility with ReplayManager
                joint_names = self.dataset.features["observation.state"]["names"]
                for name in joint_names:
                    entities.add(f"joints/{name}/angle")
            elif col.startswith("observation.pointcloud"):
                entities.add("pointcloud")
        return sorted(list(entities))

    def get_joint_names(self) -> List[str]:
        """Get joint names from dataset features."""
        if "observation.state" in self.dataset.features:
            return self.dataset.features["observation.state"]["names"]
        return []

    def get_joint_trajectory(self) -> pd.DataFrame:
        """
        Return joint state trajectory for all joints.
        """
        if "observation.state" not in self.df.columns:
            return pd.DataFrame()

        res = pd.DataFrame({"time": self.df["timestamp"]})
        state_data = np.stack(self.df["observation.state"].values)
        joint_names = self.get_joint_names()

        for i, name in enumerate(joint_names):
            res[name] = state_data[:, i]

        return res

    def get_images(self, entity_path: str, timeline: str = "sim_time") -> List[Dict]:
        """
        Load images using LeRobotDataset's decoding logic.
        """
        sanitized = entity_path.replace("/", "_")
        col_name = f"observation.images.{sanitized}"

        if col_name not in self.dataset.features:
            return []

        images = []
        # LeRobotDataset.__getitem__ handles video decoding
        for i in range(len(self.dataset)):
            item = self.dataset[i]
            # LeRobotDataset returns torch.Tensor (C, H, W)
            img_tensor = item[col_name]
            # Convert to numpy (H, W, C) BGR for OpenCV compatibility in SODA
            img_np = img_tensor.permute(1, 2, 0).numpy()
            if img_np.dtype == np.float32:
                img_np = (img_np * 255).astype(np.uint8)
            # RGB to BGR
            img_bgr = img_np[..., ::-1]

            images.append({"time": float(item["timestamp"]), "image": img_bgr})
        return images

    def get_state(self) -> pd.DataFrame:
        state_data = np.stack(self.df["observation.state"].values)

    def get_points(self, entity_path: str) -> List[Dict]:
        """
        Decode pointcloud from columns.
        Now expected to be float32 arrays.
        """
        pos_col = "observation.pointcloud.positions"
        col_col = "observation.pointcloud.colors"

        if pos_col not in self.df.columns:
            return []

        points = []
        timestamps = self.df["timestamp"].values
        pos_data = self.df[pos_col].values
        col_data = (
            self.df[col_col].values
            if col_col in self.df.columns
            else [None] * len(self.df)
        )

        for ts, pos, col in zip(timestamps, pos_data, col_data):
            if pos is None:
                continue

            positions = np.array(pos, dtype=np.float32).reshape(-1, 3)

            colors = None
            if col is not None:
                colors = np.array(col, dtype=np.float32).reshape(-1, 3)

            points.append({"time": float(ts), "positions": positions, "colors": colors})
        return points


if __name__ == "__main__":
    db_dir = "test_lerobot_official"
    if not os.path.exists(db_dir):
        print(f"Dataset {db_dir} not found.")
    else:
        reader = PandasReader(db_dir)
        print("Entities:", reader.get_all_entity_paths())
        imgs = reader.get_images("camera/rgb")
        print(f"Images found: {len(imgs)}")

        pts = reader.get_points("pointcloud")
        print(f"Point clouds found: {len(pts)}")
        if pts:
            print(f"First point cloud shape: {pts[0]['positions'].shape}")
