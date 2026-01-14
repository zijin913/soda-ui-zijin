#!/usr/bin/env python3
"""
Converter from SODA data format to LeRobot dataset format.
Does not use the lerobot library.
"""

import json
import os
import shutil
from pathlib import Path
import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from typing import Dict, List, Any


def create_info_json(root: Path, fps: int, features: Dict, robot_type: str = "soda_robot") -> None:
    """Create meta/info.json"""
    info = {
        "codebase_version": "v3.0",
        "fps": fps,
        "features": features,
        "use_videos": True,
        "robot_type": robot_type,
        "chunks_size": 1000,
        "data_files_size_in_mb": 100,
        "video_files_size_in_mb": 100,
        "total_episodes": 0,
        "total_frames": 0,
        "total_tasks": 0,
        "splits": {"train": "0:0"},
        "data_path": "data/chunk-{chunk_index}/file-{file_index}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index}/file-{file_index}.mp4",
    }
    (root / "meta").mkdir(parents=True, exist_ok=True)
    with open(root / "meta" / "info.json", "w") as f:
        json.dump(info, f, indent=2)


def create_empty_stats(root: Path) -> None:
    """Create empty meta/stats.json"""
    stats = {}
    with open(root / "meta" / "stats.json", "w") as f:
        json.dump(stats, f, indent=2)


def create_tasks_parquet(root: Path, tasks: List[str]) -> None:
    """Create meta/tasks.parquet"""
    df = pd.DataFrame({"task_index": range(len(tasks))}, index=tasks)
    (root / "meta").mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df)
    pq.write_table(table, root / "meta" / "tasks.parquet")


def convert_soda_to_lerobot(soda_pickle_path: str, lerobot_root: str, fps: int = 30):
    """
    Convert SODA pickle data to LeRobot format.
    """
    root = Path(lerobot_root)
    root.mkdir(parents=True, exist_ok=True)

    # Load SODA data
    reader = PandasReader(soda_pickle_path)

    # Get all data
    df = reader.df
    if df.empty:
        print("No data to convert")
        return

    # Get unique times
    times = sorted(df["time"].unique())

    # Get joint names (assume all revolute/continuous joints)
    joint_names = []
    for joint in reader.df[reader.df["type"] == "transform"]["entity_path"].unique():
        joint_names.append(joint)
    joint_names.sort()
    num_joints = len(joint_names)

    # Define features
    features = {
        "observation.state": {
            "dtype": "float32",
            "shape": (num_joints,),
            "names": joint_names,
        },
        "observation.images.camera": {
            "dtype": "video",
            "shape": (200, 300, 3),  # From test
            "names": None,
        },
        "action": {"dtype": "float32", "shape": (num_joints,), "names": joint_names},
        "timestamp": {"dtype": "float64", "shape": (1,), "names": None},
        "episode_index": {"dtype": "int64", "shape": (1,), "names": None},
        "task_index": {"dtype": "int64", "shape": (1,), "names": None},
        "frame_index": {"dtype": "int64", "shape": (1,), "names": None},
        "index": {"dtype": "int64", "shape": (1,), "names": None},
    }

    # Create meta files
    create_info_json(root, fps, features)
    create_empty_stats(root)
    create_tasks_parquet(root, ["soda_simulation"])

    # Prepare data
    data_rows = []
    video_files = []  # List of (src_path, dest_key)

    for frame_idx, time_val in enumerate(times):
        row = {
            "timestamp": time_val,
            "episode_index": 0,
            "task_index": 0,
            "frame_index": frame_idx,
            "index": frame_idx,
        }

        # Collect joint angles
        joint_angles = []
        for joint in joint_names:
            mask = (df["time"] == time_val) & (df["entity_path"] == joint) & (df["type"] == "transform")
            if mask.any():
                angle = df.loc[mask, "joint_angle"].iloc[0]
                joint_angles.append(angle)
            else:
                joint_angles.append(0.0)  # Default

        row["observation.state"] = np.array(joint_angles, dtype=np.float32)
        row["action"] = np.array(joint_angles, dtype=np.float32)  # Assume action = state

        # Collect image
        img_mask = (df["time"] == time_val) & (df["type"] == "image")
        if img_mask.any():
            video_path = df.loc[img_mask, "video_path"].iloc[0]
            src_video = Path(soda_pickle_path).parent / video_path
            if src_video.exists():
                dest_key = "observation.images.camera"
                video_files.append((src_video, dest_key))

        data_rows.append(row)

    # Create data parquet
    df_data = pd.DataFrame(data_rows)
    # Convert arrays to lists for parquet
    for col in df_data.columns:
        if df_data[col].dtype == object and isinstance(df_data[col].iloc[0], np.ndarray):
            df_data[col] = df_data[col].apply(lambda x: x.tolist())

    table = pa.Table.from_pandas(df_data)
    data_dir = root / "data" / "chunk-000"
    data_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, data_dir / "file-000.parquet")

    # Copy videos
    for src_video, dest_key in video_files:
        dest_dir = root / "videos" / dest_key / "chunk-000"
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_video, dest_dir / "file-000.mp4")

    # Create episodes parquet
    episodes_df = pd.DataFrame(
        {
            "episode_index": [0],
            "length": [len(data_rows)],
            "tasks": [["soda_simulation"]],
            "dataset_from_index": [0],
            "dataset_to_index": [len(data_rows)],
            "meta/episodes/chunk_index": [0],
            "meta/episodes/file_index": [0],
        }
    )
    episodes_dir = root / "meta" / "episodes" / "chunk-000"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(episodes_df)
    pq.write_table(table, episodes_dir / "file-000.parquet")

    # Update info.json with totals
    info_path = root / "meta" / "info.json"
    with open(info_path, "r") as f:
        info = json.load(f)
    info["total_episodes"] = 1
    info["total_frames"] = len(data_rows)
    info["total_tasks"] = 1
    info["splits"] = {"train": "0:1"}
    with open(info_path, "w") as f:
        json.dump(info, f, indent=2)

    print(f"Converted {len(data_rows)} frames to LeRobot format at {root}")


# Import here to avoid circular import
from soda_server.data_reader import PandasReader


if __name__ == "__main__":
    # Test conversion
    soda_pickle = "test_recording_pandas.pkl"
    lerobot_root = "test_lerobot_dataset"
    convert_soda_to_lerobot(soda_pickle, lerobot_root)
