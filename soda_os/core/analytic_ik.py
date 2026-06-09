#!/usr/bin/env python3
"""
Analytic Inverse Kinematics for HexArm L6Y robot.

Pure Python/NumPy/Pinocchio implementation without hex_robo_utils dependency.
Provides ~600x higher precision than numerical IK methods.

Based on geometric closed-form solution for 6-DOF spherical wrist robots.
"""

import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass

try:
    import pinocchio as pin
    PINOCCHIO_AVAILABLE = True
except ImportError:
    pin = None
    PINOCCHIO_AVAILABLE = False


# ==================== Utility Functions ====================

def angle_norm(angles: np.ndarray) -> np.ndarray:
    """Normalize angles to [-π, π]."""
    return np.arctan2(np.sin(angles), np.cos(angles))


def quat_to_rot(q: np.ndarray) -> np.ndarray:
    """
    Convert quaternion [w, x, y, z] to 3x3 rotation matrix.
    """
    w, x, y, z = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - w*z), 2*(x*z + w*y)],
        [2*(x*y + w*z), 1 - 2*(x*x + z*z), 2*(y*z - w*x)],
        [2*(x*z - w*y), 2*(y*z + w*x), 1 - 2*(x*x + y*y)]
    ])


def rot_to_quat(R: np.ndarray) -> np.ndarray:
    """
    Convert 3x3 rotation matrix to quaternion [w, x, y, z].
    """
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


def part2trans(pos: np.ndarray, quat: np.ndarray) -> np.ndarray:
    """
    Convert position + quaternion to 4x4 homogeneous transform.

    Args:
        pos: Position [x, y, z]
        quat: Quaternion [w, x, y, z]

    Returns:
        4x4 transformation matrix
    """
    T = np.eye(4)
    T[:3, :3] = quat_to_rot(quat)
    T[:3, 3] = pos
    return T


def trans2part(T: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert 4x4 transform to position + quaternion.

    Returns:
        (position[3], quaternion[4])
    """
    pos = T[:3, 3].copy()
    quat = rot_to_quat(T[:3, :3])
    return pos, quat


def trans_inv(T: np.ndarray) -> np.ndarray:
    """
    Compute inverse of 4x4 homogeneous transform.

    More efficient than np.linalg.inv for SE(3) matrices.
    """
    R = T[:3, :3]
    t = T[:3, 3]
    T_inv = np.eye(4)
    T_inv[:3, :3] = R.T
    T_inv[:3, 3] = -R.T @ t
    return T_inv


def single_euler2rot(angle: float, axis: str) -> np.ndarray:
    """
    Create rotation matrix from single axis rotation.

    Args:
        angle: Rotation angle in radians
        axis: 'x', 'y', or 'z'

    Returns:
        3x3 rotation matrix
    """
    c, s = np.cos(angle), np.sin(angle)
    if axis == 'x':
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    elif axis == 'y':
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    elif axis == 'z':
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    else:
        raise ValueError(f"Invalid axis: {axis}")


def rot2euler_yzx(R: np.ndarray, last_euler: Optional[np.ndarray] = None, eps: float = 1e-6) -> np.ndarray:
    """
    Convert rotation matrix to YZX Euler angles.

    Used for wrist joint decomposition (q3, q4, q5).

    Args:
        R: 3x3 rotation matrix
        last_euler: Previous euler angles for continuity
        eps: Small value for gimbal lock detection

    Returns:
        [ry, rz, rx] Euler angles in radians
    """
    # YZX decomposition: R = Ry(ry) * Rz(rz) * Rx(rx)
    # From hex_robo_utils.math_utils.rot2euler with format='yzx':
    # rz = arcsin(R[1,0])
    # ry = arctan2(-R[2,0], R[0,0])
    # rx = arctan2(-R[1,2], R[1,1])

    rz = np.arcsin(np.clip(R[1, 0], -1.0, 1.0))

    if np.abs(np.cos(rz)) > eps:
        # Non-singular case
        ry = np.arctan2(-R[2, 0], R[0, 0])
        rx = np.arctan2(-R[1, 2], R[1, 1])
    else:
        # Gimbal lock - use previous ry if available
        if last_euler is not None:
            ry = last_euler[0]
        else:
            ry = 0.0

        if rz > 1.5:  # Near +pi/2
            rx = np.arctan2(R[2, 1], R[2, 2]) - ry
        else:  # Near -pi/2
            rx = np.arctan2(R[2, 1], R[2, 2]) + ry

    result = np.array([ry, rz, rx])

    # Ensure continuity with last euler angles
    if last_euler is not None:
        for i in range(3):
            while result[i] - last_euler[i] > np.pi:
                result[i] -= 2 * np.pi
            while result[i] - last_euler[i] < -np.pi:
                result[i] += 2 * np.pi

    return result


# ==================== Analytic IK Result ====================

@dataclass
class AnalyticIKResult:
    """Result of analytic inverse kinematics computation."""
    success: bool
    joints: Optional[np.ndarray]
    error_pos: float  # Position error in meters
    error_ori: float  # Orientation error in radians
    method: str = "analytic"
    message: str = ""


# ==================== End-effector Frame Options ====================

# TCP (Tool Center Point): offset from link_6 to gripper tips
# Only position offset, no rotation (identity quaternion)
END_POSE_TCP = np.array([0.0, 0.0, 0.187, 1.0, 0.0, 0.0, 0.0])

# Link_6 frame: No offset (matches Pinocchio FK)
END_POSE_LINK6 = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0])


# ==================== Analytic IK Solver ====================

class AnalyticIKSolver:
    """
    Analytic IK solver for Firefly Y6 (6-DOF, spherical wrist; both bimanual arms identical).

    Uses Pinocchio for FK and implements closed-form IK solution
    using geometric decomposition for 6-DOF spherical wrist robots.

    Algorithm:
        1. q0: Solve using atan2(y, x) from wrist center position
        2. q1, q2: Triangle geometry with cosine law
        3. q3, q4, q5: Euler angle decomposition (YZX) from rotation matrix
    """

    def __init__(
        self,
        urdf_path: str,
        end_effector_frame: str = "link_6",
        tcp_offset: float = 0.0,
    ):
        """
        Initialize analytic IK solver.

        Args:
            urdf_path: Path to URDF file
            end_effector_frame: Name of end-effector frame in URDF
            tcp_offset: TCP offset from end-effector frame (meters)
        """
        if not PINOCCHIO_AVAILABLE:
            raise ImportError("Pinocchio is required for AnalyticIKSolver")

        # Load model with Pinocchio
        self.model = pin.buildModelFromUrdf(urdf_path)
        self.data = self.model.createData()

        # Get frame ID
        self.ee_frame = end_effector_frame
        if self.ee_frame in [f.name for f in self.model.frames]:
            self.ee_frame_id = self.model.getFrameId(self.ee_frame)
        else:
            self.ee_frame_id = self.model.nframes - 1

        # Joint limits
        self.nq = self.model.nq
        self.q_min = self.model.lowerPositionLimit.copy()
        self.q_max = self.model.upperPositionLimit.copy()

        # TCP offset
        self.tcp_offset = tcp_offset

        # Build end-effector transform
        if tcp_offset > 0:
            self._end_pose = np.array([0.0, 0.0, tcp_offset, 1.0, 0.0, 0.0, 0.0])
        else:
            self._end_pose = END_POSE_LINK6.copy()

        self._trans_end_in_last = part2trans(self._end_pose[:3], self._end_pose[3:])
        self._trans_last_in_end = trans_inv(self._trans_end_in_last)

        # Pre-compute geometric parameters
        self._analytic_params = self._compute_analytic_params()

    def _compute_analytic_params(self) -> dict:
        """Compute geometric parameters for analytic IK from zero configuration."""
        # Get FK at zero configuration
        q_zero = np.zeros(self.nq)
        fk_list = self._get_all_frame_poses(q_zero)

        # Transform values
        trans_ik0_in_base = np.eye(4)
        trans_ik0_in_base[2, 3] = fk_list[1][0][2]  # Height of joint 1

        pos_last_in_ik456 = np.array([
            fk_list[5][0][2] - fk_list[4][0][2], 0.0, 0.0
        ])
        trans_ik6_in_last = trans_inv(
            part2trans(pos_last_in_ik456, np.array([0.7071068, 0.0, 0.7071068, 0.0]))
        )
        trans_ik6_in_end = self._trans_last_in_end @ trans_ik6_in_last

        # Link lengths
        l_ik3_to_ik456 = fk_list[4][0][2] - fk_list[3][0][2]
        l1 = fk_list[1][0][0] - fk_list[0][0][0]
        l2 = fk_list[2][0][2] - fk_list[1][0][2]
        l3_x = fk_list[3][0][0] - fk_list[2][0][0]
        l3_y = fk_list[3][0][2] - fk_list[2][0][2]
        l3 = np.sqrt(l3_x**2 + l3_y**2)

        # Other parameters
        q2_offset = np.arctan2(l3_x, l3_y)
        min_norm = np.fabs(l2 - l3)
        max_norm = l2 + l3

        joint_rot_list = [
            (1.0, 0.0, "z"),
            (1.0, -0.5 * np.pi, "y"),
            (1.0, 0.0, "y"),
            (1.0, 0.0, "y"),
            (1.0, 0.0, "z"),
            (1.0, 0.0, "x"),
        ]

        return {
            "trans_ik0_in_base": trans_ik0_in_base,
            "trans_ik6_in_end": trans_ik6_in_end,
            "l_ik3_to_ik456": l_ik3_to_ik456,
            "l1": l1,
            "l2": l2,
            "l3": l3,
            "q2_offset": q2_offset,
            "min_norm": min_norm,
            "max_norm": max_norm,
            "joint_rot_list": joint_rot_list,
        }

    def _get_all_frame_poses(self, q: np.ndarray) -> list:
        """Get poses of all joint frames using Pinocchio FK."""
        pin.forwardKinematics(self.model, self.data, q)

        # Use oMi (joint placements), not oMf (frame placements)
        # oMi[0] is universe, oMi[1] is joint 1, etc.
        poses = []
        joint_num = self.model.njoints - 1  # Exclude universe joint

        for i in range(joint_num):
            pose = self.data.oMi[i + 1]  # +1 to skip universe
            pos = pose.translation.copy()
            quat = rot_to_quat(pose.rotation)
            poses.append((pos, quat))

        # Add end-effector pose (with TCP offset if any)
        if joint_num > 0:
            last_pose = self.data.oMi[joint_num].homogeneous
            ee_pose = last_pose @ self._trans_end_in_last
            pos = ee_pose[:3, 3].copy()
            quat = rot_to_quat(ee_pose[:3, :3])
            poses.append((pos, quat))

        return poses

    def forward_kinematics(self, q: np.ndarray) -> list:
        """
        Compute forward kinematics for all frames.

        Returns:
            List of (position, quaternion) tuples for each frame
        """
        return self._get_all_frame_poses(q)

    def get_limit(self) -> Tuple[np.ndarray, np.ndarray]:
        """Get joint limits."""
        return self.q_min.copy(), self.q_max.copy()

    def _triangle_theta(self, a: float, b: float, c: float) -> float:
        """Calculate angle using cosine law: cos(C) = (a^2 + b^2 - c^2) / (2ab)"""
        return np.arccos(np.clip((a**2 + b**2 - c**2) / (2.0 * a * b), -1.0, 1.0))

    def _single_joint_rot(self, q: float, idx: int) -> np.ndarray:
        """Get rotation matrix for a single joint."""
        inv, bias, axis = self._analytic_params["joint_rot_list"][idx]
        return single_euler2rot(q * inv + bias, axis)

    def inverse_kinematics_analytic(
        self,
        tar_pose: Tuple[np.ndarray, np.ndarray],
        start_q: np.ndarray,
        eps: float = 1e-3,
    ) -> Tuple[bool, np.ndarray]:
        """
        Compute analytic inverse kinematics.

        Args:
            tar_pose: Target pose as (position[3], quaternion[4]) tuple
                      quaternion format: [w, x, y, z]
            start_q: Starting joint configuration (6 joints)
            eps: Small value for numerical stability

        Returns:
            Tuple of (success, joint_angles)
        """
        ik_success = True
        result_q = start_q.copy()
        params = self._analytic_params

        # Convert target pose to transformation matrix
        trans_end_tar_in_base = part2trans(tar_pose[0], tar_pose[1])

        # Transform to IK frame
        trans_ik6_in_ik0 = (
            trans_inv(params["trans_ik0_in_base"])
            @ trans_end_tar_in_base
            @ params["trans_ik6_in_end"]
        )
        pos_ik456_in_ik0 = trans_ik6_in_ik0[:3, 3]
        rot_ik6_in_ik0 = trans_ik6_in_ik0[:3, :3]

        # Solve q0 (base rotation)
        xy_norm = np.linalg.norm(pos_ik456_in_ik0[:2])
        if xy_norm > eps:
            result_q[0] = np.arctan2(pos_ik456_in_ik0[1], pos_ik456_in_ik0[0])
            delta_q0 = result_q[0] - start_q[0]
            if delta_q0 < -1.57:
                result_q[0] += np.pi
            elif delta_q0 > 1.57:
                result_q[0] -= np.pi
        rot_ik1_in_ik0 = self._single_joint_rot(result_q[0], 0)

        # Calculate position of joint 3 in frame 1
        normal_workplane = np.array([
            -np.sin(result_q[0]),
            np.cos(result_q[0]),
            0.0,
        ])
        axis_to_proj = rot_ik6_in_ik0 @ np.array([1.0, 0.0, 0.0])
        axis_perp = np.dot(axis_to_proj, normal_workplane) * normal_workplane
        axis_in_plane = rot_ik1_in_ik0.T @ (axis_to_proj - axis_perp)
        norm_axis_in_plane = np.linalg.norm(axis_in_plane)
        axis_in_plane = axis_in_plane / (norm_axis_in_plane + 1e-9)

        pos_ik3_in_ik1 = (
            rot_ik1_in_ik0.T @ pos_ik456_in_ik0
            - axis_in_plane * params["l_ik3_to_ik456"]
            - np.array([params["l1"], 0.0, 0.0])
        )
        norm_pos_ik3_in_ik1 = np.linalg.norm(pos_ik3_in_ik1) + 1e-6

        # Check reachability
        if norm_pos_ik3_in_ik1 < params["min_norm"]:
            pos_ik3_in_ik1 = pos_ik3_in_ik1 / norm_pos_ik3_in_ik1 * params["min_norm"]
            norm_pos_ik3_in_ik1 = params["min_norm"]
            ik_success = False
        elif norm_pos_ik3_in_ik1 > params["max_norm"]:
            pos_ik3_in_ik1 = pos_ik3_in_ik1 / norm_pos_ik3_in_ik1 * params["max_norm"]
            norm_pos_ik3_in_ik1 = params["max_norm"]
            ik_success = False

        # Solve q1 and q2 using triangle geometry
        theta2 = self._triangle_theta(params["l2"], params["l3"], norm_pos_ik3_in_ik1)
        result_q[2] = np.pi - (theta2 + params["q2_offset"])
        if result_q[2] < 0.0:
            result_q[2] += 2.0 * np.pi

        theta_triangle = self._triangle_theta(
            norm_pos_ik3_in_ik1, params["l2"], params["l3"]
        )
        theta_ik4 = np.arctan2(pos_ik3_in_ik1[2], pos_ik3_in_ik1[0])
        theta1 = theta_ik4 + theta_triangle
        result_q[1] = 0.5 * np.pi - theta1

        # Solve q3, q4, q5 using rotation matrix decomposition
        rot_ik3_in_ik0 = (
            rot_ik1_in_ik0
            @ self._single_joint_rot(result_q[1], 1)
            @ self._single_joint_rot(result_q[2], 2)
        )
        rot_ik6_in_ik3 = rot_ik3_in_ik0.T @ trans_ik6_in_ik0[:3, :3]

        # YZX Euler angle decomposition
        result_q[3:6] = rot2euler_yzx(rot_ik6_in_ik3, result_q[3:6].copy())

        # Normalize angles and check limits
        result_q = angle_norm(result_q)
        lower_mask = result_q < self.q_min[:len(result_q)]
        upper_mask = result_q > self.q_max[:len(result_q)]

        if np.any(lower_mask) or np.any(upper_mask):
            ik_success = False
            result_q[lower_mask] = self.q_min[:len(result_q)][lower_mask]
            result_q[upper_mask] = self.q_max[:len(result_q)][upper_mask]

        return ik_success, result_q


def create_analytic_solver(
    urdf_path: str,
    tcp_offset: float = 0.0,
) -> AnalyticIKSolver:
    """
    Create analytic IK solver.

    Args:
        urdf_path: Path to URDF file
        tcp_offset: TCP offset from link_6 (meters).
                    Use 0.187 for gripper tip, 0.0 for link_6 frame.

    Returns:
        AnalyticIKSolver instance
    """
    return AnalyticIKSolver(
        urdf_path=urdf_path,
        end_effector_frame="link_6",
        tcp_offset=tcp_offset,
    )
