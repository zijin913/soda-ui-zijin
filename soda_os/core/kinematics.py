#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Kinematics - Forward and Inverse Kinematics
============================================

Unified kinematics interface supporting:
1. **Analytic IK** (default, recommended) - ~600x higher precision, no iteration
2. **Numerical IK** (fallback) - DLS, LM, adaptive methods

Uses Pinocchio for FK and geometric closed-form solution for analytic IK.
"""

import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Literal, Union
from dataclasses import dataclass

try:
    import pinocchio as pin
    PINOCCHIO_AVAILABLE = True
except ImportError:
    pin = None
    PINOCCHIO_AVAILABLE = False

try:
    from .analytic_ik import AnalyticIKSolver, create_analytic_solver
    ANALYTIC_IK_AVAILABLE = True
except ImportError:
    ANALYTIC_IK_AVAILABLE = False


@dataclass
class IKResult:
    """Result of inverse kinematics computation."""
    success: bool
    joints: Optional[np.ndarray]
    error_pos: float  # Position error in meters
    error_ori: float  # Orientation error in radians
    iterations: int   # 0 for analytic
    method: str
    message: str


class Kinematics:
    """
    Unified kinematics solver.

    IK Priority:
    1. Analytic (HexDynUtil) - Preferred, ~600x higher precision
    2. Numerical (Pinocchio) - Fallback for unsupported configs

    Example:
        kin = Kinematics(urdf_key="firefly_y6_gr100")  # 6-DOF arm + GR100 mass lumped

        # Forward kinematics
        T = kin.forward(joint_angles)

        # Inverse kinematics (auto-selects analytic if available)
        result = kin.solve_ik(target_xyz, q_init)
        if result.success:
            target_q = result.joints

        # Force specific method
        result = kin.solve_ik(target_xyz, q_init, method="analytic")

    Note:
        Bimanual setups should instantiate one Kinematics per arm; both
        firefly_y6 arms are kinematically identical.
    """

    def __init__(
        self,
        urdf_path: Optional[str] = None,
        urdf_key: Optional[str] = None,
        arm_type: str = "firefly_y6",
        gripper_type: str = "gr100",
        end_effector_frame: str = "link_6",
        joint_offsets: Optional[np.ndarray] = None,
        use_tcp_frame: bool = False,
        tcp_offset: float = 0.187,
    ):
        """
        Initialize kinematics solver.

        Args:
            urdf_path: Path to URDF file (overrides urdf_key)
            urdf_key: Key in HEXARM_URDF_PATH_DICT
            arm_type: Robot arm type for analytic IK
            gripper_type: Gripper type for analytic IK
            end_effector_frame: Name of end-effector frame
            joint_offsets: Offsets for URDF error compensation
            use_tcp_frame: If True, target is gripper TCP (187mm offset)
            tcp_offset: TCP offset from link_6 in meters (default: 0.187)
        """
        self.tcp_offset = tcp_offset
        self.arm_type = arm_type
        self.gripper_type = gripper_type
        self.use_tcp_frame = use_tcp_frame

        # Resolve URDF path
        if urdf_path is None:
            if urdf_key is not None:
                from hex_zmq_servers.robot.hexarm import HEXARM_URDF_PATH_DICT
                urdf_path = HEXARM_URDF_PATH_DICT.get(urdf_key)
            else:
                # Try to construct from arm_type and gripper_type
                from hex_zmq_servers.robot.hexarm import HEXARM_URDF_PATH_DICT
                key = f"{arm_type}_{gripper_type}"
                urdf_path = HEXARM_URDF_PATH_DICT.get(key)

        if urdf_path is None:
            raise ValueError("Could not resolve URDF path")

        self.urdf_path = Path(urdf_path)

        # Initialize analytic IK solver (preferred)
        self._analytic_solver = None
        if ANALYTIC_IK_AVAILABLE:
            try:
                self._init_analytic_solver()
            except Exception as e:
                print(f"Warning: Analytic IK unavailable: {e}")

        # Initialize Pinocchio for FK and numerical IK fallback
        self._pin_model = None
        self._pin_data = None
        if PINOCCHIO_AVAILABLE:
            self._init_pinocchio(end_effector_frame)

        if self._analytic_solver is None and self._pin_model is None:
            raise ImportError("Pinocchio is required for kinematics")

        # Joint info
        if self._pin_model is not None:
            self.nq = self._pin_model.nq
            self.q_min = self._pin_model.lowerPositionLimit
            self.q_max = self._pin_model.upperPositionLimit
        elif self._analytic_solver is not None:
            limits = self._analytic_solver.get_limit()
            self.q_min, self.q_max = limits
            self.nq = len(self.q_min)

        # Joint offsets
        self.joint_offsets = np.asarray(joint_offsets) if joint_offsets is not None else np.zeros(self.nq)

    def _init_analytic_solver(self):
        """Initialize analytic IK solver."""
        # TCP offset: use tcp_offset for TCP frame, 0 for link_6 frame
        offset = self.tcp_offset if self.use_tcp_frame else 0.0

        self._analytic_solver = create_analytic_solver(
            urdf_path=str(self.urdf_path),
            tcp_offset=offset,
        )

    def _init_pinocchio(self, end_effector_frame: str):
        """Initialize Pinocchio model."""
        self._pin_model = pin.buildModelFromUrdf(str(self.urdf_path))
        self._pin_data = self._pin_model.createData()

        # Get end-effector frame ID
        self.ee_frame = end_effector_frame
        if self.ee_frame in [f.name for f in self._pin_model.frames]:
            self.ee_frame_id = self._pin_model.getFrameId(self.ee_frame)
        else:
            self.ee_frame_id = self._pin_model.nframes - 1

    @property
    def has_analytic_ik(self) -> bool:
        """Check if analytic IK is available."""
        return self._analytic_solver is not None

    # ========== Forward Kinematics ==========

    def forward(self, q: np.ndarray, apply_offsets: bool = False) -> np.ndarray:
        """
        Compute forward kinematics.

        Args:
            q: Joint angles (nq,)
            apply_offsets: Apply joint offsets for URDF error compensation

        Returns:
            4x4 homogeneous transformation matrix (base -> end-effector)
        """
        q = np.asarray(q).flatten()[:self.nq]

        if apply_offsets:
            q = q + self.joint_offsets[:len(q)]

        if self._analytic_solver is not None:
            # Use analytic FK
            fk_list = self._analytic_solver.forward_kinematics(q)
            pos, quat = fk_list[-1]  # Last frame is end-effector
            # Convert quaternion [w,x,y,z] to rotation matrix
            T = np.eye(4)
            T[:3, :3] = self._quat_to_rot(quat)
            T[:3, 3] = pos
            return T
        else:
            # Use Pinocchio FK
            pin.forwardKinematics(self._pin_model, self._pin_data, q)
            pin.updateFramePlacements(self._pin_model, self._pin_data)
            pose = self._pin_data.oMf[self.ee_frame_id]
            T = np.eye(4)
            T[:3, :3] = pose.rotation
            T[:3, 3] = pose.translation
            return T

    def forward_position(self, q: np.ndarray, apply_offsets: bool = False) -> np.ndarray:
        """Get end-effector position only."""
        return self.forward(q, apply_offsets)[:3, 3]

    def forward_tcp(self, q: np.ndarray, apply_offsets: bool = False) -> np.ndarray:
        """Get TCP (gripper tip) position."""
        T = self.forward(q, apply_offsets)
        link6_pos = T[:3, 3]
        tool_axis = T[:3, 2]  # Z-axis
        return link6_pos + self.tcp_offset * tool_axis

    # ========== Inverse Kinematics ==========

    def solve_ik(
        self,
        target_pos: np.ndarray,
        target_ori: Optional[np.ndarray] = None,
        q_init: Optional[np.ndarray] = None,
        method: Literal["auto", "analytic", "numerical"] = "auto",
        max_iterations: int = 200,
        tolerance: float = 1e-3,
        verbose: bool = False,
    ) -> IKResult:
        """
        Solve inverse kinematics.

        Args:
            target_pos: Target position [x, y, z] in meters
            target_ori: Target orientation (3x3 matrix or 4-element quaternion [w,x,y,z])
                        None for position-only IK (keeps current orientation)
            q_init: Initial joint configuration
            method: "auto" (default), "analytic", or "numerical"
            max_iterations: Max iterations for numerical methods
            tolerance: Convergence tolerance (meters)
            verbose: Print progress

        Returns:
            IKResult with success status, joints, errors, etc.
        """
        if q_init is None:
            q_init = np.zeros(self.nq)
        else:
            q_init = np.asarray(q_init).flatten()[:self.nq]

        # Auto-select method
        if method == "auto":
            method = "analytic" if self.has_analytic_ik else "numerical"

        if method == "analytic":
            if not self.has_analytic_ik:
                return IKResult(False, None, float('inf'), float('inf'), 0, "analytic", "Analytic IK not available")
            return self._solve_analytic(target_pos, target_ori, q_init, verbose)
        else:
            if not PINOCCHIO_AVAILABLE:
                return IKResult(False, None, float('inf'), float('inf'), 0, "numerical", "Pinocchio not available")
            return self._solve_numerical(target_pos, target_ori, q_init, max_iterations, tolerance, verbose)

    def _solve_analytic(
        self,
        target_pos: np.ndarray,
        target_ori: Optional[np.ndarray],
        q_init: np.ndarray,
        verbose: bool,
    ) -> IKResult:
        """Solve using analytic IK (geometric closed-form)."""
        # Get target quaternion
        if target_ori is None:
            # Position-only: use current orientation
            fk_list = self._analytic_solver.forward_kinematics(q_init)
            _, current_quat = fk_list[-1]
            target_quat = current_quat
        elif target_ori.shape == (3, 3):
            # Rotation matrix to quaternion [w,x,y,z]
            target_quat = self._rot_to_quat(target_ori)
        elif target_ori.shape == (4,):
            target_quat = target_ori
        else:
            raise ValueError(f"Invalid target_ori shape: {target_ori.shape}")

        if verbose:
            fk_list = self._analytic_solver.forward_kinematics(q_init)
            current_pos = fk_list[-1][0]
            dist = np.linalg.norm(target_pos - current_pos)
            print(f"  [Analytic] Distance: {dist*1000:.1f}mm")

        # Call analytic IK
        success, result_q = self._analytic_solver.inverse_kinematics_analytic(
            (target_pos, target_quat),
            q_init
        )

        # Verify with FK
        fk_list = self._analytic_solver.forward_kinematics(result_q)
        result_pos, result_quat = fk_list[-1]

        error_pos = np.linalg.norm(result_pos - target_pos)
        dot_product = np.abs(np.dot(result_quat, target_quat))
        error_ori = 2 * np.arccos(np.clip(dot_product, -1.0, 1.0))

        if verbose:
            print(f"  [Analytic] Position error: {error_pos*1000:.3f}mm")
            print(f"  [Analytic] Orientation error: {np.rad2deg(error_ori):.2f}°")

        return IKResult(
            success=success,
            joints=result_q,
            error_pos=error_pos,
            error_ori=error_ori,
            iterations=0,
            method="analytic",
            message="OK" if success else "Joint limits reached"
        )

    def _solve_numerical(
        self,
        target_pos: np.ndarray,
        target_ori: Optional[np.ndarray],
        q_init: np.ndarray,
        max_iterations: int,
        tolerance: float,
        verbose: bool,
    ) -> IKResult:
        """Solve using numerical IK (Pinocchio DLS)."""
        position_only = target_ori is None
        lambda_damping = 1e-6

        if not position_only:
            if target_ori.shape == (4,):
                target_ori = self._quat_to_rot(target_ori)
            target_pose = pin.SE3(target_ori, target_pos)

        q = q_init.copy()
        best_q = q.copy()
        best_error = float('inf')

        for i in range(max_iterations):
            pin.forwardKinematics(self._pin_model, self._pin_data, q)
            pin.updateFramePlacements(self._pin_model, self._pin_data)
            current_pose = self._pin_data.oMf[self.ee_frame_id]

            if position_only:
                error_vec = target_pos - current_pose.translation
                error_norm = np.linalg.norm(error_vec)
                J = pin.computeFrameJacobian(
                    self._pin_model, self._pin_data, q, self.ee_frame_id, pin.LOCAL_WORLD_ALIGNED
                )[:3, :]
            else:
                error_se3 = pin.log(current_pose.inverse() * target_pose)
                error_vec = error_se3.vector
                error_norm = np.linalg.norm(error_vec[:3])  # Position part
                J = pin.computeFrameJacobian(
                    self._pin_model, self._pin_data, q, self.ee_frame_id, pin.LOCAL_WORLD_ALIGNED
                )

            if verbose and (i < 5 or i % 50 == 0):
                print(f"  [Numerical] Iter {i}: err={error_norm*1000:.1f}mm")

            if error_norm < best_error:
                best_error = error_norm
                best_q = q.copy()

            if error_norm < tolerance:
                return IKResult(True, q, error_norm, 0.0, i, "numerical", "Converged")

            JJT = J @ J.T
            n = J.shape[0]
            dq = J.T @ np.linalg.solve(JJT + lambda_damping**2 * np.eye(n), error_vec)

            step_size = min(1.0, error_norm * 5.0)
            q = pin.integrate(self._pin_model, q, dq * step_size)
            q = np.clip(q, self.q_min, self.q_max)

        return IKResult(False, best_q, best_error, 0.0, max_iterations, "numerical", f"Max iterations (best: {best_error*1000:.1f}mm)")

    # ========== Simple API (backwards compatible) ==========

    def inverse_position(
        self,
        target_position: np.ndarray,
        q_init: Optional[np.ndarray] = None,
        method: str = "auto",
    ) -> Tuple[np.ndarray, bool]:
        """Simple position-only IK. Returns (joints, success)."""
        result = self.solve_ik(target_position, None, q_init, method=method)
        return result.joints, result.success

    def inverse_position_tcp(
        self,
        target_tcp: np.ndarray,
        q_init: Optional[np.ndarray] = None,
        method: str = "auto",
    ) -> Tuple[np.ndarray, bool]:
        """
        Position-only IK for TCP (gripper tip).

        FK uses link_6 frame. This computes where link_6 should be
        to place TCP at target position.

        Args:
            target_tcp: Target position for TCP in base frame
            q_init: Initial joint configuration
            method: IK method ("auto", "analytic", "numerical")

        Returns:
            (joints, success)
        """
        if q_init is None:
            q_init = np.zeros(self.nq)
        q_init = np.asarray(q_init).flatten()[:self.nq]

        # Get tool axis from current orientation
        T = self.forward(q_init)
        tool_axis = T[:3, 2]  # Z-axis (tool direction)

        # link_6 should be tcp_offset behind TCP
        target_link6 = np.asarray(target_tcp).flatten() - self.tcp_offset * tool_axis

        return self.inverse_position(target_link6, q_init, method)

    def inverse(
        self,
        target_pose: np.ndarray,
        q_init: Optional[np.ndarray] = None,
        method: str = "auto",
    ) -> Tuple[np.ndarray, bool]:
        """Full SE(3) IK. Returns (joints, success)."""
        target_pos = target_pose[:3, 3]
        target_ori = target_pose[:3, :3]
        result = self.solve_ik(target_pos, target_ori, q_init, method=method)
        return result.joints, result.success

    # ========== Utilities ==========

    @staticmethod
    def _quat_to_rot(q: np.ndarray) -> np.ndarray:
        """Convert quaternion [w,x,y,z] to rotation matrix."""
        w, x, y, z = q
        return np.array([
            [1 - 2*(y*y + z*z), 2*(x*y - w*z), 2*(x*z + w*y)],
            [2*(x*y + w*z), 1 - 2*(x*x + z*z), 2*(y*z - w*x)],
            [2*(x*z - w*y), 2*(y*z + w*x), 1 - 2*(x*x + y*y)]
        ])

    @staticmethod
    def _rot_to_quat(R: np.ndarray) -> np.ndarray:
        """Convert rotation matrix to quaternion [w,x,y,z]."""
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

    @property
    def joint_limits(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return (lower_limits, upper_limits)."""
        return self.q_min.copy(), self.q_max.copy()

    def jacobian(self, q: np.ndarray) -> np.ndarray:
        """Compute Jacobian (requires Pinocchio)."""
        if not PINOCCHIO_AVAILABLE or self._pin_model is None:
            raise RuntimeError("Jacobian requires Pinocchio")

        q = np.asarray(q).flatten()[:self.nq]
        pin.computeJointJacobians(self._pin_model, self._pin_data, q)
        pin.updateFramePlacements(self._pin_model, self._pin_data)
        return pin.getFrameJacobian(
            self._pin_model, self._pin_data, self.ee_frame_id, pin.ReferenceFrame.LOCAL_WORLD_ALIGNED
        )

    # ========== Limit Checking ==========

    def check_joint_limits(
        self,
        joints: np.ndarray,
        margin: float = 0.0,
    ) -> Tuple[bool, str]:
        """
        Check if joint configuration is within limits.

        Args:
            joints: Joint configuration (n_joints,)
            margin: Safety margin from limits (rad)

        Returns:
            (is_valid, error_message)
        """
        joints = np.asarray(joints).flatten()[:self.nq]

        for i, q in enumerate(joints):
            lower = self.q_min[i] + margin
            upper = self.q_max[i] - margin
            if not (lower <= q <= upper):
                return False, f"Joint {i}: {q:.3f} outside [{lower:.3f}, {upper:.3f}]"

        return True, ""

    def check_workspace_limits(
        self,
        position: np.ndarray,
        workspace: dict,
    ) -> Tuple[bool, str]:
        """
        Check if Cartesian position is within workspace limits.

        Args:
            position: Target position [x, y, z] in meters
            workspace: Dictionary with 'x', 'y', 'z' ranges
                Example: {'x': [-0.5, 0.5], 'y': [-0.5, 0.5], 'z': [0.0, 0.6]}

        Returns:
            (is_valid, error_message)
        """
        position = np.asarray(position).flatten()
        axes = ['x', 'y', 'z']

        for i, axis in enumerate(axes):
            if axis in workspace:
                limits = workspace[axis]
                if not (limits[0] <= position[i] <= limits[1]):
                    return False, f"{axis.upper()}: {position[i]:.3f} outside [{limits[0]:.3f}, {limits[1]:.3f}]"

        return True, ""
