#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
CameraService - Camera Operations Service
==========================================

Provides camera operations for the frontend.
Wraps hex_zmq_servers camera client.
"""

import time
import numpy as np
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class CameraFrame:
    """Camera frame data."""
    rgb: np.ndarray  # (H, W, 3) RGB image
    depth: Optional[np.ndarray]  # (H, W) depth in meters
    timestamp: float
    intrinsics: Optional[np.ndarray]  # 3x3 camera matrix


class CameraService:
    """
    Camera service for RGB-D operations.

    Provides:
    - RGB/depth image capture
    - Point cloud generation
    - Pixel-to-3D conversion

    Example:
        service = CameraService(config)
        service.connect()

        frame = service.get_frame()
        point = service.pixel_to_3d(u, v)

        service.disconnect()
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        camera_client=None,
        cam_name: str = "left",
    ):
        """
        Initialize camera service for ONE wrist camera.

        The underlying camera driver returns dict-of-arms RGB/depth and
        intrinsics; this service slices that into a single camera and
        exposes a flat single-camera API.

        For dual-wrist setups create two CameraService instances, one
        per wrist (``cam_name`` in {"left", "right"}).

        Args:
            config: Configuration dictionary
            camera_client: Optional pre-configured camera driver (dual-arm
                dict-of-arms shape)
            cam_name: Which wrist camera to slice ("left" or "right")
        """
        self.config = config or {}
        self._client = camera_client
        self._connected = False
        self._intrinsics: Optional[np.ndarray] = None
        self._cam_name = cam_name

        # Frame freshness tracking
        self._last_new_frame_time: float = 0.0
        self._cached_rgb: Optional[np.ndarray] = None
        self._cached_depth: Optional[np.ndarray] = None
        self._stale_threshold: float = self.config.get("stale_threshold", 1.0)  # seconds

    def connect(self) -> bool:
        """
        Connect to camera server.

        Supports both simulation and real hardware via DriverFactory.
        Set config["mode"] = "sim" for simulation, "real" for real hardware.

        Returns:
            True if connected successfully
        """
        if self._client is None:
            # Create driver via DriverFactory
            from ..drivers import DriverFactory

            mode = self.config.get("mode", "real")  # Default to real hardware
            driver_config = {
                "sim": self.config.get("sim", {
                    "ip": "127.0.0.1",
                    "port": 12345,
                    "robot_type": "l6y",
                }),
                "camera": self.config.get("camera", {
                    "ip": "127.0.0.1",
                    "port": 12346,
                }),
            }

            self._factory = DriverFactory(mode=mode, config=driver_config)
            self._client = self._factory.create_camera_driver()

        try:
            # Connect
            if not self._client.connect():
                self._connected = False
                return False

            # Driver returns dict-of-arms intrinsics; pick our slice.
            intri_all = self._client.get_intrinsics()
            if isinstance(intri_all, dict):
                self._intrinsics = intri_all.get(self._cam_name)
            else:
                self._intrinsics = intri_all  # legacy / single-arm driver
            self._connected = True
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from camera server."""
        if self._client is not None:
            self._client.disconnect()
            self._client = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if connected to camera."""
        return self._connected

    @property
    def intrinsics(self) -> Optional[np.ndarray]:
        """Get camera intrinsic matrix."""
        return self._intrinsics

    @property
    def frame_age(self) -> float:
        """Time since last new frame was received (seconds)."""
        if self._last_new_frame_time == 0:
            return float('inf')
        return time.time() - self._last_new_frame_time

    @property
    def is_frame_stale(self) -> bool:
        """Check if frame is stale (no new frame for too long)."""
        return self.frame_age > self._stale_threshold

    def get_rgb(self, use_cache: bool = True) -> Optional[np.ndarray]:
        """
        Get RGB image with automatic caching.

        Args:
            use_cache: If True, return cached frame when no new frame available

        Returns:
            RGB image (H, W, 3) or None if failed
        """
        if not self._connected:
            return None

        try:
            rgb_all = self._client.get_rgb()
            rgb = rgb_all.get(self._cam_name) if isinstance(rgb_all, dict) else rgb_all
            if rgb is not None:
                # New frame received
                self._last_new_frame_time = time.time()
                self._cached_rgb = rgb
                return rgb
            elif use_cache and self._cached_rgb is not None:
                # Return cached frame
                return self._cached_rgb
            return None
        except Exception as e:
            print(f"Failed to get RGB: {e}")
            return self._cached_rgb if use_cache else None

    def get_depth(self, use_cache: bool = True) -> Optional[np.ndarray]:
        """Get depth image (meters), with caching for sparse-fresh streams.

        The underlying sim/real driver runs in realtime_mode where a tight
        back-to-back read returns ``None`` because the same frame was
        already consumed. Without caching, point-cloud generation (which
        calls ``get_rgb()`` then ``get_depth()`` in quick succession)
        almost always misses on the depth call. With ``use_cache=True``
        we fall back to the last successfully-fetched depth frame.
        """
        if not self._connected:
            return None

        try:
            depth_all = self._client.get_depth()
            depth = depth_all.get(self._cam_name) if isinstance(depth_all, dict) else depth_all
            # Driver should already deliver meters, but be defensive.
            if depth is not None and depth.dtype == np.uint16:
                depth = depth.astype(np.float32) / 1000.0
            if depth is not None:
                self._cached_depth = depth
                return depth
            if use_cache and self._cached_depth is not None:
                return self._cached_depth
            return None
        except Exception as e:
            print(f"Failed to get depth: {e}")
            return self._cached_depth if use_cache else None

    def get_frame(self) -> Optional[CameraFrame]:
        """
        Get RGB + depth frame.

        Returns:
            CameraFrame or None if failed
        """
        rgb = self.get_rgb()
        if rgb is None:
            return None

        depth = self.get_depth()

        return CameraFrame(
            rgb=rgb,
            depth=depth,
            timestamp=0.0,  # TODO: get actual timestamp
            intrinsics=self._intrinsics,
        )

    def get_depth_at_pixel(self, u: int, v: int) -> Optional[float]:
        """
        Get depth value at a specific pixel.

        Args:
            u: Pixel x coordinate
            v: Pixel y coordinate

        Returns:
            Depth in meters or None
        """
        depth = self.get_depth()
        if depth is None:
            return None

        h, w = depth.shape
        if not (0 <= v < h and 0 <= u < w):
            return None

        return float(depth[v, u])

    def pixel_to_3d(
        self,
        u: float,
        v: float,
        depth: Optional[float] = None,
    ) -> Optional[np.ndarray]:
        """
        Convert pixel to 3D point in camera frame.

        Args:
            u: Pixel x coordinate
            v: Pixel y coordinate
            depth: Optional depth value (reads from depth image if None)

        Returns:
            3D point (3,) in camera frame, or None if failed
        """
        if self._intrinsics is None:
            print("Camera intrinsics not available")
            return None

        if depth is None:
            depth = self.get_depth_at_pixel(int(u), int(v))
            if depth is None or depth <= 0:
                return None

        fx, fy = self._intrinsics[0, 0], self._intrinsics[1, 1]
        cx, cy = self._intrinsics[0, 2], self._intrinsics[1, 2]

        x = (u - cx) * depth / fx
        y = (v - cy) * depth / fy
        z = depth

        return np.array([x, y, z])

    def get_point_cloud(
        self,
        rgb: Optional[np.ndarray] = None,
        depth: Optional[np.ndarray] = None,
        downsample: int = 1,
    ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """
        Generate point cloud from RGB-D.

        Args:
            rgb: RGB image (optional, fetches if None)
            depth: Depth image (optional, fetches if None)
            downsample: Downsampling factor (1 = no downsampling)

        Returns:
            (points, colors): Points (N, 3) and colors (N, 3) or None
        """
        if self._intrinsics is None:
            return None

        if rgb is None:
            rgb = self.get_rgb()
        if depth is None:
            depth = self.get_depth()

        if rgb is None or depth is None:
            return None

        h, w = depth.shape
        fx, fy = self._intrinsics[0, 0], self._intrinsics[1, 1]
        cx, cy = self._intrinsics[0, 2], self._intrinsics[1, 2]

        # Create pixel grids
        u = np.arange(0, w, downsample)
        v = np.arange(0, h, downsample)
        u, v = np.meshgrid(u, v)

        # Sample depth and RGB
        depth_sampled = depth[::downsample, ::downsample]
        rgb_sampled = rgb[::downsample, ::downsample]

        # Filter valid depth. Default 10 m matches soda-zijin and excludes
        # MuJoCo's ``zfar`` plane (50 m sky pixels) — otherwise the wrist
        # camera, when pointed at the sky, fills the cloud with useless
        # far-away points that visually dilute the table coverage.
        depth_max = float(self.config.get("depth_max", 10.0))
        valid = (depth_sampled > 0) & (depth_sampled < depth_max)

        u_valid = u[valid]
        v_valid = v[valid]
        z = depth_sampled[valid]

        # Compute 3D points
        x = (u_valid - cx) * z / fx
        y = (v_valid - cy) * z / fy

        points = np.stack([x, y, z], axis=-1)
        # Convert BGR to RGB (camera returns BGR)
        colors = rgb_sampled[valid][:, ::-1] / 255.0

        return points, colors

    def get_point_cloud_in_base_frame(
        self,
        T_gripper2base: np.ndarray,
        T_cam2gripper: np.ndarray,
        downsample: int = 8,
    ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """
        Get point cloud transformed to robot base frame.

        Args:
            T_gripper2base: 4x4 transform from gripper to base (from FK)
            T_cam2gripper: 4x4 transform from camera to gripper (from calibration)
            downsample: Downsampling factor

        Returns:
            (points, colors) in base frame, or None
        """
        result = self.get_point_cloud(downsample=downsample)
        if result is None:
            return None

        points_cam, colors = result
        if len(points_cam) == 0:
            return None

        # T_cam2base = T_gripper2base @ T_cam2gripper
        T_cam2base = T_gripper2base @ T_cam2gripper

        # Transform: P_base = R @ P_cam + t
        R = T_cam2base[:3, :3]
        t = T_cam2base[:3, 3]
        points_base = (R @ points_cam.T).T + t

        return points_base, colors

    @property
    def resolution(self) -> Optional[Tuple[int, int]]:
        """Get camera resolution (width, height)."""
        return (
            self.config.get("resolution", {}).get("width"),
            self.config.get("resolution", {}).get("height"),
        )
