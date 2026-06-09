#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
RobotService — high-level control for ONE arm.

Operates on a single arm slice of the dual-arm dict-of-arms driver
(see ``RobotDriverBase``). Selects the slice via the ``arm_name``
ctor arg (``"left"`` or ``"right"``).

For bimanual workflows wrap two instances in
:class:`soda_os.services.dual_arm_service.DualArmRobotService` — or
share one driver between two services through the ``robot_client``
parameter.
"""

import numpy as np
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

from ..core.kinematics import Kinematics
from ..core.transforms import Transforms
from ..core.calibration import CalibrationManager
from ..core.dynamics import Dynamics
from ..core.planning import TrajectoryGenerator, MotionPrimitives, Trajectory


@dataclass
class RobotState:
    """Robot state snapshot."""
    joint_positions: np.ndarray
    joint_velocities: np.ndarray
    joint_torques: np.ndarray
    ee_position: np.ndarray
    ee_rotation: np.ndarray
    timestamp: float


@dataclass
class GripperConfig:
    """Gripper configuration."""
    open_position: float = 0.0      # Fully open
    close_position: float = 1.335   # Fully closed
    default_duration: float = 0.5   # Default motion duration


class RobotService:
    """
    High-level robot control service.

    Combines:
    - ZMQ client for hardware communication
    - Kinematics for FK/IK
    - Transforms for coordinate conversions
    - Motion primitives for common operations

    Example:
        service = RobotService(config)
        service.connect()

        # Get current state
        state = service.get_state()

        # Move to position
        success = service.move_to_point([0.3, 0.1, 0.2])

        # Execute trajectory
        service.execute_trajectory(trajectory)

        service.disconnect()
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        robot_client=None,
        calibration_path: Optional[str] = None,
        arm_name: str = "left",
    ):
        """
        Initialize robot service for ONE arm.

        The underlying driver (sim or real) returns dict-of-arms states /
        accepts dict-of-arms commands; this service slices that into a
        single arm (``arm_name``) and exposes it as a flat single-arm API.

        For bimanual workflows wrap two instances in
        :class:`DualArmRobotService`, or share one driver between two
        services via the ``robot_client`` parameter.

        Args:
            config: Configuration dictionary
            robot_client: Optional pre-configured robot driver (already a
                dual-arm dict-of-arms driver)
            calibration_path: Path to calibration file
            arm_name: Which arm slice to drive ("left" or "right")
        """
        self.config = config or {}
        self._client = robot_client
        self._connected = False
        self._arm_name = arm_name

        # Initialize components
        self._init_kinematics()
        self._init_dynamics()
        self._init_calibration(calibration_path)
        self._init_transforms()
        self._init_motion()
        self._init_gripper()

    def _init_kinematics(self) -> None:
        """Initialize kinematics solver."""
        # Use 6-DOF URDF for IK (arm only, gripper controlled separately)
        # FK always uses link_6 frame to match hand-eye calibration
        # firefly_y6_gr100 is the 6-DOF arm-only URDF with GR100 mass lumped
        # into link_6 (no separate gripper joints). Matches the real-hardware
        # SDK which reports dofs=6 (no gripper found). Use y6_gr100 only for
        # visualization where the 8-DOF full-gripper model is useful.
        urdf_key = self.config.get("urdf", "firefly_y6_gr100")
        ee_frame = self.config.get("end_effector_frame", "link_6")
        tcp_offset = self.config.get("tcp_offset", 0.187)  # 187mm default

        try:
            self.kinematics = Kinematics(
                urdf_key=urdf_key,
                end_effector_frame=ee_frame,
                use_tcp_frame=False,  # FK uses link_6 (matches calibration)
                tcp_offset=tcp_offset,
            )
            self._arm_dof = self.kinematics.nq  # Should be 6
        except Exception as e:
            print(f"Warning: Failed to initialize kinematics: {e}")
            self.kinematics = None
            self._arm_dof = 6

    def _init_dynamics(self) -> None:
        """Initialize dynamics solver for gravity compensation."""
        arm_type = self.config.get("arm_type", "firefly_y6")
        gripper_type = self.config.get("gripper_type", "gr100")

        try:
            self.dynamics = Dynamics(arm_type=arm_type, gripper_type=gripper_type)
        except Exception as e:
            print(f"Warning: Failed to initialize dynamics: {e}")
            self.dynamics = None

    def _init_calibration(self, calibration_path: Optional[str]) -> None:
        """Initialize calibration manager."""
        self.calibration = CalibrationManager()

        if calibration_path:
            try:
                self.calibration.load(calibration_path)
            except Exception as e:
                print(f"Warning: Failed to load calibration: {e}")

    def _init_transforms(self) -> None:
        """Initialize transforms."""
        self.transforms = Transforms()

        if self.calibration.is_loaded:
            self.transforms.set_hand_eye(self.calibration.T_cam2gripper)

    def _init_motion(self) -> None:
        """Initialize motion primitives."""
        if self.kinematics is None:
            self.motion = None
            return

        home_pos = self.config.get("home_position")
        if home_pos:
            home_pos = np.array(home_pos)

        # Read control.rate from the nested config
        control_cfg = self.config.get("control", {})
        control_rate = control_cfg.get("rate", 500.0)

        self.motion = MotionPrimitives(
            kinematics=self.kinematics,
            home_position=home_pos,
            default_duration=self.config.get("default_duration", 2.0),
            control_rate=control_rate,
        )

    def _init_gripper(self) -> None:
        """Initialize gripper configuration."""
        gripper_cfg = self.config.get("gripper", {})
        self.gripper_config = GripperConfig(
            open_position=gripper_cfg.get("open_position", 0.0),
            close_position=gripper_cfg.get("close_position", 1.335),
            default_duration=gripper_cfg.get("default_duration", 0.5),
        )

    def connect(self) -> bool:
        """
        Connect to robot server.

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
                "robot": self.config.get("robot", {
                    "ip": "127.0.0.1",
                    "port": 12345,
                }),
            }

            self._factory = DriverFactory(mode=mode, config=driver_config)
            self._client = self._factory.create_robot_driver()

        try:
            # Connect and test
            if not self._client.connect():
                self._connected = False
                return False

            dofs = self._client.get_dofs()
            self._connected = dofs is not None

            # In sim mode the driver knows the exact camera-to-gripper
            # transform from the MJCF model. Driver returns dict-of-arms;
            # pick our arm's slice.
            if self._connected and hasattr(self._client, "get_cam2gripper"):
                T_sim_all = self._client.get_cam2gripper()
                T_sim = T_sim_all.get(self._arm_name) if isinstance(T_sim_all, dict) else T_sim_all
                if T_sim is not None:
                    self.calibration.T_cam2gripper = T_sim
                    self.transforms.set_hand_eye(T_sim)

            return self._connected
        except Exception as e:
            print(f"Failed to connect: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from robot server."""
        if self._client is not None:
            self._client.disconnect()
            self._client = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if connected to robot."""
        return self._connected

    def get_state(self) -> Optional[RobotState]:
        """
        Get current robot state.

        Returns:
            RobotState or None if not connected
        """
        if not self._connected:
            return None

        try:
            # Read ONLY this arm's client. Reading both arms here lets two
            # parallel callers (e.g. left/right go_home threads, or the teleop
            # state-grab loop) steal each other's realtime frame — the loser
            # gets None and aborts. Per-arm reads keep each frame for its owner.
            states = self._client.get_states(self._arm_name)
            if states is None:
                return None

            # Driver returns {self._arm_name: {...}} for a per-arm read.
            arm_states = states.get(self._arm_name) if isinstance(states, dict) else None
            if not isinstance(arm_states, dict):
                return None

            q = np.asarray(arm_states.get("position", np.zeros(7)))
            qd = np.asarray(arm_states.get("velocity", np.zeros(7)))
            tau = np.asarray(arm_states.get("torque", np.zeros(7)))

            # Compute FK using arm joints only (first 6)
            ee_pos = np.zeros(3)
            ee_rot = np.eye(3)
            if self.kinematics:
                q_arm = q[:self._arm_dof]
                T = self.kinematics.forward(q_arm)
                ee_pos = T[:3, 3]
                ee_rot = T[:3, :3]

            return RobotState(
                joint_positions=q,
                joint_velocities=qd,
                joint_torques=tau,
                ee_position=ee_pos,
                ee_rotation=ee_rot,
                timestamp=arm_states.get("timestamp", 0.0),
            )
        except Exception as e:
            print(f"Failed to get state: {e}")
            return None

    def get_joint_positions(self) -> Optional[np.ndarray]:
        """Get current joint positions."""
        state = self.get_state()
        return state.joint_positions if state else None

    def get_ee_position(self) -> Optional[np.ndarray]:
        """Get current end-effector position."""
        state = self.get_state()
        return state.ee_position if state else None

    def move_to_joints(
        self,
        target_q: np.ndarray,
        duration: Optional[float] = None,
        blocking: bool = True,
        current_q: Optional[np.ndarray] = None,
    ) -> bool:
        """
        Move to target joint positions (arm joints only).

        Args:
            target_q: Target joint angles (arm only, 6 DOF)
            duration: Motion duration
            blocking: Wait for completion
            current_q: Optional current joint positions (avoids re-fetching)

        Returns:
            True if successful
        """
        if not self._connected or self.motion is None:
            return False

        if current_q is None:
            current_q = self.get_joint_positions()
            if current_q is None:
                return False

        # Use only arm joints for trajectory
        target_arm = np.asarray(target_q).flatten()[:self._arm_dof]
        current_arm = current_q[:self._arm_dof]

        traj = self.motion.move_to_joints(target_arm, current_arm, duration)

        # Store gripper position to preserve during execution
        self._gripper_position = current_q[self._arm_dof:] if len(current_q) > self._arm_dof else None

        return self.execute_trajectory(traj, blocking)

    def move_to_point(
        self,
        target_xyz: np.ndarray,
        duration: Optional[float] = None,
        blocking: bool = True,
    ) -> Tuple[bool, bool]:
        """
        Move end-effector to target position (arm joints only).

        Args:
            target_xyz: Target position in base frame
            duration: Motion duration
            blocking: Wait for completion

        Returns:
            (execution_success, ik_success)
        """
        if not self._connected or self.motion is None:
            return False, False

        current_q = self.get_joint_positions()
        if current_q is None:
            return False, False

        # Use only arm joints for IK and trajectory
        current_arm = current_q[:self._arm_dof]
        traj, ik_success = self.motion.move_to_point(target_xyz, current_arm, duration)

        # Store gripper position to preserve during execution
        self._gripper_position = current_q[self._arm_dof:] if len(current_q) > self._arm_dof else None

        exec_success = self.execute_trajectory(traj, blocking)

        return exec_success, ik_success

    def move_to_pixel(
        self,
        u: float,
        v: float,
        depth: float,
        camera_intrinsics: np.ndarray,
        duration: Optional[float] = None,
        blocking: bool = True,
    ) -> Tuple[bool, bool]:
        """
        Move to a point specified by pixel coordinates.

        Requires calibration to be loaded.

        Args:
            u: Pixel x coordinate
            v: Pixel y coordinate
            depth: Depth at pixel (meters)
            camera_intrinsics: 3x3 camera matrix
            duration: Motion duration
            blocking: Wait for completion

        Returns:
            (execution_success, ik_success)
        """
        if not self.calibration.is_loaded:
            print("Calibration not loaded")
            return False, False

        current_q = self.get_joint_positions()
        if current_q is None:
            return False, False

        # Get current gripper pose from FK
        T_gripper2base = self.kinematics.forward(current_q)

        # Transform pixel to base frame
        target_xyz = self.transforms.pixel_to_base(
            u, v, depth, camera_intrinsics, T_gripper2base
        )

        return self.move_to_point(target_xyz, duration, blocking)

    def go_home(
        self,
        duration: Optional[float] = None,
        blocking: bool = True,
        home_position: Optional[np.ndarray] = None,
    ) -> bool:
        """
        Move to home position (arm joints only).

        Args:
            duration: Motion duration
            blocking: Wait for completion
            home_position: Optional per-call home override (arm joints). When
                given it wins over the configured home, so a caller can pin the
                exact pose it will later verify against.

        Returns:
            True if successful
        """
        if not self._connected or self.motion is None:
            return False

        if home_position is None and self.motion.home_position is None:
            print("Home position not set")
            return False

        current_q = self.get_joint_positions()
        if current_q is None:
            return False

        # Use only arm joints
        current_arm = current_q[:self._arm_dof]

        # Store gripper position to preserve during execution
        self._gripper_position = current_q[self._arm_dof:] if len(current_q) > self._arm_dof else None

        traj = self.motion.go_home(current_arm, duration, home_position=home_position)
        return self.execute_trajectory(traj, blocking)

    def execute_trajectory(
        self,
        trajectory: Trajectory,
        blocking: bool = True,
        max_position_error: float = 0.5,
        max_velocity: float = 5.0,  # 5 rad/s is reasonable for most robots
        use_gravity_compensation: bool = True,
    ) -> bool:
        """
        Execute a trajectory with time control and safety checks.

        Args:
            trajectory: Trajectory to execute (arm joints only)
            blocking: Wait for completion (if False, only sends first command)
            max_position_error: Maximum allowed position tracking error (rad)
            max_velocity: Maximum allowed joint velocity (rad/s)
            use_gravity_compensation: Add gravity compensation feedforward torque

        Returns:
            True if execution completed successfully
        """
        import time

        if not self._connected:
            return False

        # Check if gravity compensation is available
        use_grav = use_gravity_compensation and self.dynamics is not None

        # Get gripper position to append (set by move_to_joints/move_to_point)
        gripper_pos = getattr(self, '_gripper_position', None)

        def make_full_cmd(arm_q, tau_ff=None):
            """Create command with position and optional feedforward torque."""
            # Append gripper position
            if gripper_pos is not None and len(gripper_pos) > 0:
                full_q = np.concatenate([arm_q, gripper_pos])
            else:
                full_q = arm_q

            # Add feedforward torque column if provided
            if tau_ff is not None:
                if gripper_pos is not None and len(gripper_pos) > 0:
                    full_tau = np.concatenate([tau_ff[:len(arm_q)], np.zeros(len(gripper_pos))])
                else:
                    full_tau = tau_ff[:len(arm_q)]
                return np.column_stack([full_q, full_tau])

            return full_q

        if not blocking:
            # Non-blocking: just send first position
            try:
                q_arm = trajectory.positions[0]
                tau_ff = self.dynamics.gravity(q_arm) if use_grav else None
                cmd = make_full_cmd(q_arm, tau_ff)
                self._client.set_cmds({self._arm_name: cmd})
                return True
            except Exception as e:
                print(f"Failed to start trajectory: {e}")
                return False

        # Blocking execution with time control
        try:
            start_time = time.time()
            n_points = len(trajectory.timestamps)

            for i, (t, q_arm) in enumerate(zip(trajectory.timestamps, trajectory.positions)):
                # Wait until it's time for this waypoint
                elapsed = time.time() - start_time
                if elapsed < t:
                    time.sleep(t - elapsed)

                # Safety check: get current state and verify
                state = self.get_state()
                if state is not None:
                    # Check position tracking error (arm joints only)
                    current_arm = state.joint_positions[:len(q_arm)]
                    pos_error = np.max(np.abs(current_arm - q_arm))
                    if pos_error > max_position_error:
                        print(f"[STOP] Position error {pos_error:.3f} rad exceeds limit")
                        self.stop()
                        return False

                    # Check velocity (arm joints only)
                    max_vel = np.max(np.abs(state.joint_velocities[:len(q_arm)]))
                    if max_vel > max_velocity:
                        print(f"[STOP] Velocity {max_vel:.3f} rad/s exceeds limit")
                        self.stop()
                        return False

                # Compute gravity compensation
                tau_ff = self.dynamics.gravity(q_arm) if use_grav else None

                # Send command (position + feedforward torque)
                cmd = make_full_cmd(q_arm, tau_ff)
                self._client.set_cmds({self._arm_name: cmd})

                # Progress (every 10%)
                if i % max(1, n_points // 10) == 0:
                    progress = (i / n_points) * 100
                    print(f"  Trajectory: {progress:.0f}%")

            print("  Trajectory: 100%")
            return True

        except Exception as e:
            print(f"Trajectory execution failed: {e}")
            self.stop()
            return False

    def stop(self) -> bool:
        """
        Stop robot motion (hold current position).

        Returns:
            True if successful
        """
        if not self._connected:
            return False

        try:
            current_q = self.get_joint_positions()
            if current_q is not None:
                self._client.set_cmds({self._arm_name: current_q})
            return True
        except Exception:
            return False

    def get_joint_limits(self) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Get joint position limits."""
        if self.kinematics:
            return self.kinematics.joint_limits
        return None

    # ==================== Gripper Control ====================

    def get_gripper_position(self) -> Optional[float]:
        """
        Get current gripper position.

        Returns:
            Gripper position (0.0=open, 1.335=closed) or None if failed
        """
        state = self.get_state()
        if state is None:
            return None

        # Gripper is joint index 6 (7th joint)
        if len(state.joint_positions) > self._arm_dof:
            return float(state.joint_positions[self._arm_dof])
        return None

    def set_gripper(
        self,
        position: float,
        duration: Optional[float] = None,
        blocking: bool = True,
    ) -> bool:
        """
        Set gripper to specific position.

        Args:
            position: Target position (0.0=open, 1.335=closed)
            duration: Motion duration (uses default if None)
            blocking: Wait for completion

        Returns:
            True if successful
        """
        if not self._connected:
            return False

        # Clamp to valid range
        position = np.clip(
            position,
            self.gripper_config.open_position,
            self.gripper_config.close_position,
        )

        duration = duration or self.gripper_config.default_duration

        try:
            # Get current state
            state = self.get_state()
            if state is None:
                return False

            current_q = state.joint_positions

            # Ensure we have gripper joint
            if len(current_q) <= self._arm_dof:
                print("No gripper joint found")
                return False

            # Generate gripper trajectory
            current_gripper = current_q[self._arm_dof]
            control_rate = self.config.get("control_rate", 500.0)
            n_steps = max(2, int(duration * control_rate))

            # Linear interpolation for gripper
            gripper_traj = np.linspace(current_gripper, position, n_steps)

            # Check if gravity compensation is available
            use_grav = self.dynamics is not None

            if not blocking:
                # Non-blocking: send target position immediately with gravity compensation
                cmd = current_q.copy()
                cmd[self._arm_dof] = position
                if use_grav:
                    tau_ff = self.dynamics.gravity(current_q[:self._arm_dof])
                    tau_full = np.concatenate([tau_ff, np.zeros(len(current_q) - self._arm_dof)])
                    cmd = np.column_stack([cmd, tau_full])
                self._client.set_cmds({self._arm_name: cmd})
                return True

            # Blocking: execute trajectory with gravity compensation
            import time
            dt = duration / n_steps

            for i, gripper_pos in enumerate(gripper_traj):
                # Get latest arm state to maintain position
                state = self.get_state()
                if state is not None:
                    arm_q = state.joint_positions[:self._arm_dof]
                else:
                    arm_q = current_q[:self._arm_dof]

                # Build command: current arm position + target gripper position
                cmd = np.concatenate([arm_q, [gripper_pos]])

                # Add gravity compensation feedforward torque
                if use_grav:
                    tau_ff = self.dynamics.gravity(arm_q)
                    tau_full = np.concatenate([tau_ff, np.zeros(1)])
                    cmd = np.column_stack([cmd, tau_full])

                self._client.set_cmds({self._arm_name: cmd})
                time.sleep(dt)

                # Progress (every 25%)
                if i % max(1, n_steps // 4) == 0:
                    progress = (i / n_steps) * 100
                    print(f"  Gripper: {progress:.0f}%")

            print("  Gripper: 100%")
            return True

        except Exception as e:
            print(f"Gripper control failed: {e}")
            return False

    def open_gripper(
        self,
        duration: Optional[float] = None,
        blocking: bool = True,
    ) -> bool:
        """
        Open gripper fully.

        Args:
            duration: Motion duration
            blocking: Wait for completion

        Returns:
            True if successful
        """
        print("[Gripper] Opening...")
        return self.set_gripper(
            self.gripper_config.open_position,
            duration,
            blocking,
        )

    def close_gripper(
        self,
        duration: Optional[float] = None,
        blocking: bool = True,
    ) -> bool:
        """
        Close gripper fully.

        Args:
            duration: Motion duration
            blocking: Wait for completion

        Returns:
            True if successful
        """
        print("[Gripper] Closing...")
        return self.set_gripper(
            self.gripper_config.close_position,
            duration,
            blocking,
        )
