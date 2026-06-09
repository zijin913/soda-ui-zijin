#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Transforms - Coordinate Frame Transformations
==============================================

Handles coordinate transformations between frames:
- Camera frame
- Gripper/End-effector frame
- Robot base frame
- World frame

Consolidates coordinate-transform helpers used across the kinematics/calibration stack.
"""

import numpy as np
from typing import Optional, Tuple


class Transforms:
    """
    Coordinate transformation utilities.

    Frame conventions:
    - Camera: Z forward, X right, Y down (OpenCV convention)
    - Robot base: Typically Z up, X forward
    - Gripper: Depends on URDF definition

    Example:
        tf = Transforms()
        tf.set_hand_eye(T_cam2gripper)

        # Transform point from camera to base
        p_base = tf.camera_to_base(p_camera, T_gripper2base)

        # Transform pixel to 3D point in base frame
        p_base = tf.pixel_to_base(u, v, depth, K, T_gripper2base)
    """

    def __init__(self, T_cam2gripper: Optional[np.ndarray] = None):
        """
        Initialize transforms.

        Args:
            T_cam2gripper: 4x4 hand-eye calibration matrix (camera -> gripper)
        """
        self._T_cam2gripper = T_cam2gripper

    def set_hand_eye(self, T_cam2gripper: np.ndarray) -> None:
        """Set hand-eye calibration transform."""
        self._T_cam2gripper = np.asarray(T_cam2gripper)

    @property
    def T_cam2gripper(self) -> Optional[np.ndarray]:
        """Get hand-eye calibration transform."""
        return self._T_cam2gripper

    def camera_to_gripper(self, p_camera: np.ndarray) -> np.ndarray:
        """
        Transform point(s) from camera frame to gripper frame.

        Args:
            p_camera: Point(s) in camera frame, shape (3,) or (N, 3)

        Returns:
            Point(s) in gripper frame
        """
        if self._T_cam2gripper is None:
            raise ValueError("Hand-eye calibration not set. Call set_hand_eye() first.")

        return self._transform_points(p_camera, self._T_cam2gripper)

    def camera_to_base(
        self, p_camera: np.ndarray, T_gripper2base: np.ndarray
    ) -> np.ndarray:
        """
        Transform point(s) from camera frame to robot base frame.

        Args:
            p_camera: Point(s) in camera frame
            T_gripper2base: 4x4 gripper-to-base transform (from FK)

        Returns:
            Point(s) in base frame
        """
        p_gripper = self.camera_to_gripper(p_camera)
        return self._transform_points(p_gripper, T_gripper2base)

    def pixel_to_camera(
        self,
        u: float,
        v: float,
        depth: float,
        K: np.ndarray,
    ) -> np.ndarray:
        """
        Convert pixel coordinates + depth to 3D point in camera frame.

        Args:
            u: Pixel x coordinate
            v: Pixel y coordinate
            depth: Depth value (meters)
            K: 3x3 camera intrinsic matrix

        Returns:
            3D point in camera frame (3,)
        """
        K = np.asarray(K)
        fx, fy = K[0, 0], K[1, 1]
        cx, cy = K[0, 2], K[1, 2]

        x = (u - cx) * depth / fx
        y = (v - cy) * depth / fy
        z = depth

        return np.array([x, y, z])

    def pixel_to_base(
        self,
        u: float,
        v: float,
        depth: float,
        K: np.ndarray,
        T_gripper2base: np.ndarray,
    ) -> np.ndarray:
        """
        Convert pixel coordinates + depth to 3D point in robot base frame.

        This is the main function for click-to-move applications.

        Args:
            u: Pixel x coordinate
            v: Pixel y coordinate
            depth: Depth value (meters)
            K: 3x3 camera intrinsic matrix
            T_gripper2base: 4x4 gripper-to-base transform (from FK)

        Returns:
            3D point in robot base frame (3,)
        """
        p_camera = self.pixel_to_camera(u, v, depth, K)
        return self.camera_to_base(p_camera, T_gripper2base)

    def base_to_camera(
        self, p_base: np.ndarray, T_gripper2base: np.ndarray
    ) -> np.ndarray:
        """
        Transform point(s) from base frame to camera frame.

        Args:
            p_base: Point(s) in base frame
            T_gripper2base: 4x4 gripper-to-base transform (from FK)

        Returns:
            Point(s) in camera frame
        """
        if self._T_cam2gripper is None:
            raise ValueError("Hand-eye calibration not set.")

        T_base2gripper = np.linalg.inv(T_gripper2base)
        T_gripper2cam = np.linalg.inv(self._T_cam2gripper)
        T_base2cam = T_gripper2cam @ T_base2gripper

        return self._transform_points(p_base, T_base2cam)

    def project_to_pixel(
        self,
        p_camera: np.ndarray,
        K: np.ndarray,
    ) -> Tuple[float, float]:
        """
        Project 3D point in camera frame to pixel coordinates.

        Args:
            p_camera: 3D point in camera frame (3,)
            K: 3x3 camera intrinsic matrix

        Returns:
            (u, v) pixel coordinates
        """
        K = np.asarray(K)
        p = np.asarray(p_camera).flatten()

        if p[2] <= 0:
            raise ValueError("Point is behind camera (z <= 0)")

        u = K[0, 0] * p[0] / p[2] + K[0, 2]
        v = K[1, 1] * p[1] / p[2] + K[1, 2]

        return float(u), float(v)

    @staticmethod
    def _transform_points(points: np.ndarray, T: np.ndarray) -> np.ndarray:
        """
        Apply 4x4 transformation to point(s).

        Args:
            points: Points, shape (3,) or (N, 3)
            T: 4x4 homogeneous transformation

        Returns:
            Transformed points, same shape as input
        """
        points = np.asarray(points)
        T = np.asarray(T)
        single_point = points.ndim == 1

        if single_point:
            points = points.reshape(1, 3)

        # Apply rotation and translation
        R = T[:3, :3]
        t = T[:3, 3]
        transformed = (R @ points.T).T + t

        if single_point:
            return transformed.flatten()
        return transformed

    @staticmethod
    def pose_to_matrix(position: np.ndarray, rotation: np.ndarray) -> np.ndarray:
        """
        Convert position + rotation to 4x4 matrix.

        Args:
            position: Translation (3,)
            rotation: Rotation matrix (3,3) or quaternion (4,) [w,x,y,z]

        Returns:
            4x4 homogeneous transformation
        """
        T = np.eye(4)
        T[:3, 3] = position

        rotation = np.asarray(rotation)
        if rotation.shape == (3, 3):
            T[:3, :3] = rotation
        elif rotation.shape == (4,):
            # Quaternion [w, x, y, z]
            T[:3, :3] = Transforms.quaternion_to_rotation(rotation)
        else:
            raise ValueError(f"Invalid rotation shape: {rotation.shape}")

        return T

    @staticmethod
    def matrix_to_pose(T: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Extract position and rotation from 4x4 matrix.

        Returns:
            (position, rotation_matrix)
        """
        T = np.asarray(T)
        return T[:3, 3].copy(), T[:3, :3].copy()

    @staticmethod
    def quaternion_to_rotation(q: np.ndarray) -> np.ndarray:
        """
        Convert quaternion [w, x, y, z] to rotation matrix.
        """
        q = np.asarray(q).flatten()
        w, x, y, z = q

        R = np.array([
            [1 - 2*(y*y + z*z), 2*(x*y - w*z), 2*(x*z + w*y)],
            [2*(x*y + w*z), 1 - 2*(x*x + z*z), 2*(y*z - w*x)],
            [2*(x*z - w*y), 2*(y*z + w*x), 1 - 2*(x*x + y*y)]
        ])
        return R

    @staticmethod
    def rotation_to_quaternion(R: np.ndarray) -> np.ndarray:
        """
        Convert rotation matrix to quaternion [w, x, y, z].
        """
        R = np.asarray(R)
        trace = np.trace(R)

        if trace > 0:
            s = 0.5 / np.sqrt(trace + 1.0)
            w = 0.25 / s
            x = (R[2, 1] - R[1, 2]) * s
            y = (R[0, 2] - R[2, 0]) * s
            z = (R[1, 0] - R[0, 1]) * s
        elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
            s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
            w = (R[2, 1] - R[1, 2]) / s
            x = 0.25 * s
            y = (R[0, 1] + R[1, 0]) / s
            z = (R[0, 2] + R[2, 0]) / s
        elif R[1, 1] > R[2, 2]:
            s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
            w = (R[0, 2] - R[2, 0]) / s
            x = (R[0, 1] + R[1, 0]) / s
            y = 0.25 * s
            z = (R[1, 2] + R[2, 1]) / s
        else:
            s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
            w = (R[1, 0] - R[0, 1]) / s
            x = (R[0, 2] + R[2, 0]) / s
            y = (R[1, 2] + R[2, 1]) / s
            z = 0.25 * s

        return np.array([w, x, y, z])
