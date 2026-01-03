#!/usr/bin/env python3
"""
URDF Logger using Pandas (Single-process).
Replaces DuckDB with Pandas for data storage.
Videos are written to disk in real-time.
"""

from __future__ import annotations

import contextlib
import io
import os
import time
from pathlib import Path
from typing import Optional, Dict, Union, Any, List

import numpy as np
import pandas as pd
import scipy.spatial.transform as st
from urdf_parser_py import urdf as urdf_parser
from moviepy.video.io.ffmpeg_writer import FFMPEG_VideoWriter

class URDFLogger:
    def __init__(
        self,
        filepath: str,
        entity_path_prefix: str = "",
        db_path: str = "robot_data.parquet", # using .parquet extension by default or directory
        truncate: bool = False,
    ) -> None:
        
        # db_path acts as the base filename for the recording
        self.base_path = Path(db_path)
        self.output_dir = self.base_path.parent
        self.stem = self.base_path.stem
        
        if truncate:
            # Cleanup existing files if needed (optional)
            pass

        # Single buffer for all data types
        self.data_buffer = []

        # Video Writers
        self.video_dir = self.output_dir / (self.stem + "_videos")
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.video_writers = {} # {entity_path: {'writer': FFMPEG_VideoWriter, 'frame_idx': int, 'rel_path': str}}

        # URDF Parsing
        self.filepath = filepath
        self.entity_path_prefix = entity_path_prefix
        
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            if str(filepath).endswith("xacro"):
                try:
                    import xacro
                    xacro_doc = xacro.parse(open(filepath, encoding="utf-8"))
                    xacro.process_doc(xacro_doc)
                    self.urdf = urdf_parser.URDF.from_xml_string(xacro_doc.toxml())
                except ImportError:
                     print("[Warning] xacro library not found, trying to load as raw XML")
                     self.urdf = urdf_parser.URDF.from_xml_file(filepath)
            else:
                self.urdf = urdf_parser.URDF.from_xml_file(filepath)

        self.link_map = {link.name: link for link in self.urdf.links}
        self.joint_map = {joint.name: joint for joint in self.urdf.joints}
        
        print(f"[URDFLogger] Initialized. Logging to {self.output_dir} (Pandas backend, single dataframe)")

    def update_joints(self, joint_positions: Dict[str, float], time_seconds: Optional[float] = None) -> None:
        """Update joint states and record transforms."""
        if time_seconds is None:
            time_seconds = time.time()

        for joint_name, angle in joint_positions.items():
            if joint_name not in self.joint_map:
                continue

            joint = self.joint_map[joint_name]
            child_link_name = joint.child
            child_link = self.link_map[child_link_name]
            entity_path = self._get_link_entity_path(child_link)

            origin_xyz = np.array(joint.origin.xyz) if (joint.origin and joint.origin.xyz) else np.zeros(3)
            origin_rpy = np.array(joint.origin.rpy) if (joint.origin and joint.origin.rpy) else np.zeros(3)
            base_rot = st.Rotation.from_euler("xyz", origin_rpy)

            if joint.type in ["revolute", "continuous"]:
                axis = np.array(joint.axis) if joint.axis else np.array([1, 0, 0])
                rot_vec = axis * angle
                joint_rot = st.Rotation.from_rotvec(rot_vec)
                final_rot = base_rot * joint_rot
            else:
                final_rot = base_rot

            quat = final_rot.as_quat() # x, y, z, w
            
            self.data_buffer.append({
                "time": time_seconds,
                "entity_path": entity_path,
                "type": "transform",
                "tx": origin_xyz[0], "ty": origin_xyz[1], "tz": origin_xyz[2],
                "qx": quat[0], "qy": quat[1], "qz": quat[2], "qw": quat[3]
            })

    def log_image(self, entity_path: str, image: np.ndarray, time_seconds: Optional[float] = None):
        """Log image (write to video file immediately)."""
        if time_seconds is None:
            time_seconds = time.time()
            
        if entity_path not in self.video_writers:
            h, w = image.shape[:2]
            rel_video_path = f"{entity_path.replace('/', '_')}.mp4"
            abs_video_path = self.video_dir / rel_video_path
            
            try:
                writer_obj = FFMPEG_VideoWriter(
                    str(abs_video_path), 
                    size=(w, h), 
                    fps=30.0, 
                    codec='libx264', 
                    preset='ultrafast',
                    pixel_format='yuv420p'
                )
                self.video_writers[entity_path] = {
                    'writer': writer_obj,
                    'frame_idx': 0,
                    'rel_path': f"{self.stem}_videos/{rel_video_path}"
                }
            except Exception as e:
                print(f"[URDFLogger] Error initializing video writer for {entity_path}: {e}")
                self.video_writers[entity_path] = None
        
        writer_info = self.video_writers[entity_path]
        if writer_info is not None:
            try:
                # Convert BGR to RGB
                if image.ndim == 3 and image.shape[2] == 3:
                    image_rgb = image[..., ::-1]
                else:
                    image_rgb = image
                    
                writer_info['writer'].write_frame(image_rgb)
                
                self.data_buffer.append({
                    "time": time_seconds,
                    "entity_path": entity_path,
                    "type": "image",
                    "video_path": writer_info['rel_path'],
                    "frame_idx": writer_info['frame_idx']
                })
                
                writer_info['frame_idx'] += 1
            except Exception as e:
                print(f"[URDFLogger] Video Write Error: {e}")

    def log_points(self, entity_path: str, positions: np.ndarray, colors: Optional[np.ndarray] = None, time_seconds: Optional[float] = None):
        """Log point cloud."""
        if time_seconds is None:
            time_seconds = time.time()

        pos_blob = positions.astype(np.float32).tobytes()
        col_blob = colors.tobytes() if colors is not None else None
        
        self.data_buffer.append({
            "time": time_seconds,
            "entity_path": entity_path,
            "type": "point",
            "positions": pos_blob,
            "colors": col_blob
        })

    def log_scalar(self, entity_path: str, value: float, time_seconds: Optional[float] = None):
        """Log scalar value."""
        if time_seconds is None:
            time_seconds = time.time()
            
        self.data_buffer.append({
            "time": time_seconds,
            "entity_path": entity_path,
            "type": "scalar",
            "value": float(value)
        })

    def close(self):
        """Save buffer to disk and close resources."""
        print("[URDFLogger] Saving data...")
        
        if self.data_buffer:
            df = pd.DataFrame(self.data_buffer)
            
            # Save to single pickle file
            output_path = self.base_path
            if not output_path.suffix == ".pkl":
                output_path = output_path.with_suffix(".pkl")
                
            try:
                df.to_pickle(output_path)
                print(f"[URDFLogger] Saved to {output_path}")
            except Exception as e:
                print(f"[URDFLogger] Failed to save pickle: {e}")
        else:
             print("[URDFLogger] No data to save.")

        # Close video writers
        for writer_info in self.video_writers.values():
            if writer_info:
                try:
                    writer_info['writer'].close()
                except:
                    pass
        
        print("[URDFLogger] Closed.")

    def _get_link_entity_path(self, link: urdf_parser.Link) -> str:
        root_name = self.urdf.get_root()
        try:
            link_names = self.urdf.get_chain(root_name, link.name)[0::2]
        except KeyError:
            link_names = [link.name]
            
        path = "/".join(link_names)
        if self.entity_path_prefix:
            return f"{self.entity_path_prefix}/{path}"
        return path

# ==========================================
# Test
# ==========================================
def main():
    urdf_file = "assets/xpkg_urdf_archer_l6y/xpkg_urdf_archer_l6y.urdf"
    db_file = "test_recording_pandas" # Will create test_recording_pandas_transforms.parquet etc.
    
    if not os.path.exists(urdf_file):
        potential = "public/l6y_gp100/l6y_gp100.urdf"
        if os.path.exists(potential):
            urdf_file = potential
        else:
            print("URDF file not found.")
            return

    logger = URDFLogger(urdf_file, db_path=db_file, truncate=True)

    print("Animation starting...")
    angle_deg = 0.0
    
    try:
        for i in range(100):
            current_time = time.time()
            angle_rad = np.deg2rad(angle_deg)

            joint_angles = {}
            for joint in logger.urdf.joints:
                if joint.type in ["revolute", "continuous"]:
                    joint_angles[joint.name] = angle_rad

            logger.update_joints(joint_angles, time_seconds=current_time)
            
            logger.log_scalar("scalar/sine", np.sin(angle_rad), time_seconds=current_time)

            dummy_img = np.zeros((200, 300, 3), dtype=np.uint8)
            x = int(50 + 50 * np.sin(angle_rad))
            dummy_img[x:x+50, x:x+50] = (0, 255, 0)
            logger.log_image("camera/front", dummy_img, time_seconds=current_time)

            time.sleep(0.01) 
            angle_deg += 1.0

        print("Done.")
    finally:
        logger.close()

if __name__ == "__main__":
    main()
