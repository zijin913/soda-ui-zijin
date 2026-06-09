#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Motion Algorithms - Trajectory Generation and Motion Primitives
================================================================

Provides:
- TrajectoryGenerator: Smooth trajectory interpolation
- MotionPrimitives: Common motion patterns (move_to, home, etc.)
"""

import numpy as np
from typing import List, Tuple, Optional, Callable
from dataclasses import dataclass


@dataclass
class Trajectory:
    """Trajectory data structure."""
    positions: np.ndarray  # (N, nq) joint positions
    velocities: np.ndarray  # (N, nq) joint velocities
    timestamps: np.ndarray  # (N,) time stamps
    duration: float  # Total duration


class TrajectoryGenerator:
    """
    Smooth trajectory generator.

    Supports:
    - Minimum jerk (5th order polynomial)
    - Trapezoidal velocity profile
    - Linear interpolation

    Example:
        gen = TrajectoryGenerator()
        traj = gen.minimum_jerk(q_start, q_end, duration=2.0, rate=500)

        for i, (q, qd, t) in enumerate(zip(traj.positions, traj.velocities, traj.timestamps)):
            robot.set_position(q)
    """

    @staticmethod
    def minimum_jerk(
        q_start: np.ndarray,
        q_end: np.ndarray,
        duration: float = 2.0,
        rate: float = 500.0,
    ) -> Trajectory:
        """
        Generate minimum jerk trajectory.

        Smooth trajectory with zero velocity and acceleration at endpoints.
        Uses 5th order polynomial: s(t) = 10τ³ - 15τ⁴ + 6τ⁵

        Args:
            q_start: Start joint positions (nq,)
            q_end: End joint positions (nq,)
            duration: Trajectory duration (seconds)
            rate: Control rate (Hz)

        Returns:
            Trajectory object with positions, velocities, timestamps
        """
        q_start = np.asarray(q_start).flatten()
        q_end = np.asarray(q_end).flatten()

        n_steps = int(duration * rate) + 1
        timestamps = np.linspace(0, duration, n_steps)

        positions = []
        velocities = []

        for t in timestamps:
            tau = t / duration
            # Position: s = 10τ³ - 15τ⁴ + 6τ⁵
            s = 10 * tau**3 - 15 * tau**4 + 6 * tau**5
            # Velocity: ds/dt = (30τ² - 60τ³ + 30τ⁴) / duration
            ds = (30 * tau**2 - 60 * tau**3 + 30 * tau**4) / duration

            q = q_start + s * (q_end - q_start)
            qd = ds * (q_end - q_start)

            positions.append(q)
            velocities.append(qd)

        return Trajectory(
            positions=np.array(positions),
            velocities=np.array(velocities),
            timestamps=timestamps,
            duration=duration,
        )

    @staticmethod
    def trapezoidal(
        q_start: np.ndarray,
        q_end: np.ndarray,
        max_velocity: float = 1.0,
        max_acceleration: float = 2.0,
        rate: float = 500.0,
    ) -> Trajectory:
        """
        Generate trapezoidal velocity profile trajectory.

        Accelerates to max velocity, cruises, then decelerates.

        Args:
            q_start: Start positions
            q_end: End positions
            max_velocity: Maximum joint velocity (rad/s)
            max_acceleration: Maximum acceleration (rad/s²)
            rate: Control rate (Hz)

        Returns:
            Trajectory object
        """
        q_start = np.asarray(q_start).flatten()
        q_end = np.asarray(q_end).flatten()
        delta = q_end - q_start

        # Find the joint that takes longest
        max_delta = np.max(np.abs(delta))
        if max_delta < 1e-6:
            # No movement needed
            return Trajectory(
                positions=np.array([q_start]),
                velocities=np.array([np.zeros_like(q_start)]),
                timestamps=np.array([0.0]),
                duration=0.0,
            )

        # Time to accelerate to max velocity
        t_accel = max_velocity / max_acceleration
        # Distance covered during acceleration
        d_accel = 0.5 * max_acceleration * t_accel**2

        if 2 * d_accel >= max_delta:
            # Triangle profile (no cruise phase)
            t_accel = np.sqrt(max_delta / max_acceleration)
            duration = 2 * t_accel
        else:
            # Trapezoidal profile
            d_cruise = max_delta - 2 * d_accel
            t_cruise = d_cruise / max_velocity
            duration = 2 * t_accel + t_cruise

        n_steps = int(duration * rate) + 1
        timestamps = np.linspace(0, duration, n_steps)

        positions = []
        velocities = []

        for t in timestamps:
            if t < t_accel:
                # Acceleration phase
                s = 0.5 * max_acceleration * t**2 / max_delta
                v = max_acceleration * t / max_delta
            elif t < duration - t_accel:
                # Cruise phase
                s = (d_accel + max_velocity * (t - t_accel)) / max_delta
                v = max_velocity / max_delta
            else:
                # Deceleration phase
                t_dec = duration - t
                s = 1.0 - 0.5 * max_acceleration * t_dec**2 / max_delta
                v = max_acceleration * t_dec / max_delta

            q = q_start + s * delta
            qd = v * delta

            positions.append(q)
            velocities.append(qd)

        return Trajectory(
            positions=np.array(positions),
            velocities=np.array(velocities),
            timestamps=timestamps,
            duration=duration,
        )

    @staticmethod
    def linear(
        q_start: np.ndarray,
        q_end: np.ndarray,
        duration: float = 2.0,
        rate: float = 500.0,
    ) -> Trajectory:
        """
        Generate linear interpolation trajectory.

        Simple but may have discontinuous velocity at endpoints.

        Args:
            q_start: Start positions
            q_end: End positions
            duration: Duration (seconds)
            rate: Control rate (Hz)

        Returns:
            Trajectory object
        """
        q_start = np.asarray(q_start).flatten()
        q_end = np.asarray(q_end).flatten()

        n_steps = int(duration * rate) + 1
        timestamps = np.linspace(0, duration, n_steps)

        positions = np.array([
            q_start + (t / duration) * (q_end - q_start)
            for t in timestamps
        ])

        velocities = np.array([
            (q_end - q_start) / duration
            for _ in timestamps
        ])

        return Trajectory(
            positions=positions,
            velocities=velocities,
            timestamps=timestamps,
            duration=duration,
        )

    @staticmethod
    def waypoints(
        waypoints: List[np.ndarray],
        durations: List[float],
        method: str = "minimum_jerk",
        rate: float = 500.0,
    ) -> Trajectory:
        """
        Generate trajectory through multiple waypoints.

        Args:
            waypoints: List of joint positions
            durations: Duration for each segment
            method: Interpolation method
            rate: Control rate

        Returns:
            Combined trajectory
        """
        if len(waypoints) < 2:
            raise ValueError("Need at least 2 waypoints")
        if len(durations) != len(waypoints) - 1:
            raise ValueError("Need one duration per segment")

        gen_func = {
            "minimum_jerk": TrajectoryGenerator.minimum_jerk,
            "trapezoidal": TrajectoryGenerator.trapezoidal,
            "linear": TrajectoryGenerator.linear,
        }.get(method)

        if gen_func is None:
            raise ValueError(f"Unknown method: {method}")

        all_positions = []
        all_velocities = []
        all_timestamps = []
        t_offset = 0.0

        for i in range(len(waypoints) - 1):
            if method == "minimum_jerk":
                seg = gen_func(waypoints[i], waypoints[i + 1], durations[i], rate)
            else:
                seg = gen_func(waypoints[i], waypoints[i + 1], rate=rate)

            # Skip first point of subsequent segments to avoid duplicates
            start_idx = 1 if i > 0 else 0

            all_positions.extend(seg.positions[start_idx:])
            all_velocities.extend(seg.velocities[start_idx:])
            all_timestamps.extend(seg.timestamps[start_idx:] + t_offset)

            t_offset += seg.duration

        return Trajectory(
            positions=np.array(all_positions),
            velocities=np.array(all_velocities),
            timestamps=np.array(all_timestamps),
            duration=t_offset,
        )


class MotionPrimitives:
    """
    High-level motion primitives.

    Provides common robot motions as reusable building blocks.

    Example:
        primitives = MotionPrimitives(kinematics, home_position)

        # Move to a point
        traj = primitives.move_to_point(target_xyz, current_q)

        # Go home
        traj = primitives.go_home(current_q)
    """

    def __init__(
        self,
        kinematics,  # Kinematics instance
        home_position: Optional[np.ndarray] = None,
        default_duration: float = 2.0,
        control_rate: float = 500.0,
    ):
        """
        Initialize motion primitives.

        Args:
            kinematics: Kinematics solver instance
            home_position: Default home joint position
            default_duration: Default motion duration
            control_rate: Control rate (Hz)
        """
        self.kin = kinematics
        self.home_position = home_position
        self.default_duration = default_duration
        self.control_rate = control_rate
        self.trajectory_gen = TrajectoryGenerator()

    def move_to_joints(
        self,
        target_q: np.ndarray,
        current_q: np.ndarray,
        duration: Optional[float] = None,
        method: str = "minimum_jerk",
    ) -> Trajectory:
        """
        Move to target joint positions.

        Args:
            target_q: Target joint angles
            current_q: Current joint angles
            duration: Motion duration (uses default if None)
            method: Trajectory method

        Returns:
            Trajectory to execute
        """
        duration = duration or self.default_duration

        if method == "minimum_jerk":
            return TrajectoryGenerator.minimum_jerk(
                current_q, target_q, duration, self.control_rate
            )
        elif method == "trapezoidal":
            return TrajectoryGenerator.trapezoidal(
                current_q, target_q, rate=self.control_rate
            )
        else:
            return TrajectoryGenerator.linear(
                current_q, target_q, duration, self.control_rate
            )

    def move_to_point(
        self,
        target_xyz: np.ndarray,
        current_q: np.ndarray,
        duration: Optional[float] = None,
    ) -> Tuple[Trajectory, bool]:
        """
        Move end-effector to target 3D point.

        Uses position-only IK to find target joint angles.

        Args:
            target_xyz: Target position (3,)
            current_q: Current joint angles
            duration: Motion duration

        Returns:
            (trajectory, ik_success): Trajectory and IK convergence flag
        """
        target_q, success = self.kin.inverse_position(target_xyz, current_q)

        if not success:
            # Return trajectory to closest reachable point
            pass

        traj = self.move_to_joints(target_q, current_q, duration)
        return traj, success

    def go_home(
        self,
        current_q: np.ndarray,
        duration: Optional[float] = None,
        home_position: Optional[np.ndarray] = None,
    ) -> Trajectory:
        """
        Move to home position.

        Args:
            current_q: Current joint angles
            duration: Motion duration
            home_position: Optional per-call override of the configured home.
                When provided, takes precedence over ``self.home_position`` —
                lets a caller (e.g. teleop) impose its own home so there is a
                single source of truth instead of relying on backend config.

        Returns:
            Trajectory to home position
        """
        target = home_position if home_position is not None else self.home_position
        if target is None:
            raise ValueError("Home position not set")

        return self.move_to_joints(np.asarray(target), current_q, duration)

    def linear_motion(
        self,
        direction: np.ndarray,
        distance: float,
        current_q: np.ndarray,
        duration: Optional[float] = None,
        n_waypoints: int = 10,
    ) -> Tuple[Trajectory, bool]:
        """
        Move in a straight line in Cartesian space.

        Args:
            direction: Unit direction vector (3,)
            distance: Distance to move (meters)
            current_q: Current joint angles
            duration: Motion duration
            n_waypoints: Number of intermediate waypoints

        Returns:
            (trajectory, success): Trajectory and success flag
        """
        direction = np.asarray(direction).flatten()
        direction = direction / np.linalg.norm(direction)

        # Get current position
        current_pos = self.kin.forward_position(current_q)

        # Generate Cartesian waypoints
        waypoints_xyz = [
            current_pos + direction * distance * (i / (n_waypoints - 1))
            for i in range(n_waypoints)
        ]

        # Solve IK for each waypoint
        waypoints_q = [current_q]
        all_success = True

        for xyz in waypoints_xyz[1:]:
            q, success = self.kin.inverse_position(xyz, waypoints_q[-1])
            if not success:
                all_success = False
            waypoints_q.append(q)

        # Generate trajectory through joint waypoints
        duration = duration or self.default_duration
        segment_duration = duration / (len(waypoints_q) - 1)
        durations = [segment_duration] * (len(waypoints_q) - 1)

        traj = TrajectoryGenerator.waypoints(
            waypoints_q, durations, method="minimum_jerk", rate=self.control_rate
        )

        return traj, all_success
