#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Dynamics - Robot Dynamics and Gravity Compensation
===================================================

Provides dynamics computation for robot control:
- Gravity compensation torque
- Coriolis and centrifugal forces
- Full inverse dynamics (RNEA)

Uses Pinocchio directly for all computations (no hex_robo_utils dependency).
"""

import numpy as np
from typing import Optional, Tuple
from pathlib import Path

try:
    import pinocchio as pin
    PINOCCHIO_AVAILABLE = True
except ImportError:
    PINOCCHIO_AVAILABLE = False


class Dynamics:
    """
    Robot dynamics solver.

    Provides gravity compensation and dynamics computation using Pinocchio.

    Example:
        dyn = Dynamics(arm_type="firefly_y6", gripper_type="gr100")

        # Gravity compensation
        tau_g = dyn.gravity(joint_pos)

        # Full compensation (gravity + Coriolis)
        tau = dyn.compensation(joint_pos, joint_vel)
    """

    def __init__(
        self,
        arm_type: str = "firefly_y6",
        gripper_type: str = "gr100",
        urdf_path: Optional[str] = None,
        gravity: np.ndarray = np.array([0, 0, -9.81]),
    ):
        """
        Initialize dynamics solver (per-arm; both bimanual arms share defaults).

        Args:
            arm_type: Robot arm type (default ``firefly_y6``)
            gripper_type: Gripper type (``gr100`` lumps GR100 mass into link_6;
                          ``empty`` is bare arm)
            urdf_path: Optional custom URDF path
            gravity: Gravity vector (default: [0, 0, -9.81])
        """
        if not PINOCCHIO_AVAILABLE:
            raise ImportError("pinocchio not available for dynamics")

        self.arm_type = arm_type
        self.gripper_type = gripper_type
        self.has_gripper = gripper_type != "empty"

        # Resolve URDF path
        if urdf_path is None:
            from hex_zmq_servers.robot.hexarm import HEXARM_URDF_PATH_DICT
            model_key = f"{arm_type}_{gripper_type}"
            if model_key not in HEXARM_URDF_PATH_DICT:
                raise ValueError(f"Unknown model: {model_key}")
            urdf_path = HEXARM_URDF_PATH_DICT[model_key]

        self.urdf_path = urdf_path

        # Initialize Pinocchio model
        self._model = pin.buildModelFromUrdf(urdf_path)
        self._data = self._model.createData()

        # Set gravity
        self._model.gravity.linear = gravity.copy()

        # Cache arm DOF
        self._arm_dof = 6

    def gravity(self, joint_pos: np.ndarray) -> np.ndarray:
        """
        Compute gravity compensation torque.

        Args:
            joint_pos: Joint positions (6 or 7 DOF)

        Returns:
            Gravity compensation torque (same DOF as input)
        """
        joint_pos = np.asarray(joint_pos).flatten()

        # Extract arm joints
        arm_q = joint_pos[:self._arm_dof]

        # Compute gravity vector using Pinocchio
        g_vec = pin.computeGeneralizedGravity(self._model, self._data, arm_q)

        # Append zero for gripper if needed
        if len(joint_pos) > self._arm_dof:
            return np.concatenate([g_vec, np.zeros(len(joint_pos) - self._arm_dof)])

        return g_vec

    def compensation(
        self,
        joint_pos: np.ndarray,
        joint_vel: np.ndarray,
        include_coriolis: bool = True,
    ) -> np.ndarray:
        """
        Compute full compensation torque (gravity + Coriolis).

        Args:
            joint_pos: Joint positions (6 or 7 DOF)
            joint_vel: Joint velocities (6 or 7 DOF)
            include_coriolis: Include Coriolis/centrifugal terms

        Returns:
            Compensation torque (same DOF as input)
        """
        joint_pos = np.asarray(joint_pos).flatten()
        joint_vel = np.asarray(joint_vel).flatten()

        # Extract arm joints
        arm_q = joint_pos[:self._arm_dof]
        arm_dq = joint_vel[:self._arm_dof]

        # Compute gravity
        g_vec = pin.computeGeneralizedGravity(self._model, self._data, arm_q)

        if include_coriolis:
            # Compute Coriolis matrix: C(q, dq)
            c_mat = pin.computeCoriolisMatrix(self._model, self._data, arm_q, arm_dq)
            tau = c_mat @ arm_dq + g_vec
        else:
            tau = g_vec

        # Append zero for gripper if needed
        if len(joint_pos) > self._arm_dof:
            return np.concatenate([tau, np.zeros(len(joint_pos) - self._arm_dof)])

        return tau

    def inverse_dynamics(
        self,
        joint_pos: np.ndarray,
        joint_vel: np.ndarray,
        joint_acc: np.ndarray,
    ) -> np.ndarray:
        """
        Compute full inverse dynamics (RNEA): tau = M*qdd + C*qd + g

        Args:
            joint_pos: Joint positions
            joint_vel: Joint velocities
            joint_acc: Joint accelerations

        Returns:
            Required joint torques
        """
        joint_pos = np.asarray(joint_pos).flatten()
        joint_vel = np.asarray(joint_vel).flatten()
        joint_acc = np.asarray(joint_acc).flatten()

        arm_q = joint_pos[:self._arm_dof]
        arm_dq = joint_vel[:self._arm_dof]
        arm_ddq = joint_acc[:self._arm_dof]

        # Use RNEA (Recursive Newton-Euler Algorithm) for full inverse dynamics
        # This computes tau = M*qdd + C*qd + g efficiently in one pass
        tau = pin.rnea(self._model, self._data, arm_q, arm_dq, arm_ddq)

        if len(joint_pos) > self._arm_dof:
            return np.concatenate([tau, np.zeros(len(joint_pos) - self._arm_dof)])

        return tau

    def mass_matrix(self, joint_pos: np.ndarray) -> np.ndarray:
        """
        Compute the joint-space mass matrix M(q).

        Args:
            joint_pos: Joint positions

        Returns:
            Mass matrix (nq x nq)
        """
        joint_pos = np.asarray(joint_pos).flatten()
        arm_q = joint_pos[:self._arm_dof]

        # Compute mass matrix using CRBA (Composite Rigid Body Algorithm)
        M = pin.crba(self._model, self._data, arm_q)
        return M.copy()

    def coriolis_matrix(
        self,
        joint_pos: np.ndarray,
        joint_vel: np.ndarray,
    ) -> np.ndarray:
        """
        Compute the Coriolis matrix C(q, dq).

        Args:
            joint_pos: Joint positions
            joint_vel: Joint velocities

        Returns:
            Coriolis matrix (nq x nq)
        """
        joint_pos = np.asarray(joint_pos).flatten()
        joint_vel = np.asarray(joint_vel).flatten()

        arm_q = joint_pos[:self._arm_dof]
        arm_dq = joint_vel[:self._arm_dof]

        C = pin.computeCoriolisMatrix(self._model, self._data, arm_q, arm_dq)
        return C.copy()

    def dynamic_params(
        self,
        joint_pos: np.ndarray,
        joint_vel: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Compute all dynamic parameters: M, C, g.

        Args:
            joint_pos: Joint positions
            joint_vel: Joint velocities

        Returns:
            Tuple of (mass_matrix, coriolis_matrix, gravity_vector)
        """
        joint_pos = np.asarray(joint_pos).flatten()
        joint_vel = np.asarray(joint_vel).flatten()

        arm_q = joint_pos[:self._arm_dof]
        arm_dq = joint_vel[:self._arm_dof]

        # Compute all terms
        M = pin.crba(self._model, self._data, arm_q)
        C = pin.computeCoriolisMatrix(self._model, self._data, arm_q, arm_dq)
        g = pin.computeGeneralizedGravity(self._model, self._data, arm_q)

        return M.copy(), C.copy(), g.copy()

    @property
    def arm_dof(self) -> int:
        """Number of arm DOFs (excluding gripper)."""
        return self._arm_dof

    @property
    def model(self):
        """Access to Pinocchio model (for advanced usage)."""
        return self._model

    @property
    def data(self):
        """Access to Pinocchio data (for advanced usage)."""
        return self._data
