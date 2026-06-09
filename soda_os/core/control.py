#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Control Algorithms - PD Control
================================

Provides PD control computation for trajectory tracking.
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass


@dataclass
class PDGains:
    """PD controller gains configuration."""
    kp: np.ndarray  # Proportional gains (n_joints,)
    kd: np.ndarray  # Derivative gains (n_joints,)
    max_torque: Optional[np.ndarray] = None  # Torque limits (n_joints,)


def compute_pd_torque(
    target_pos: np.ndarray,
    target_vel: np.ndarray,
    current_pos: np.ndarray,
    current_vel: np.ndarray,
    kp: np.ndarray,
    kd: np.ndarray,
    max_torque: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Compute PD control torque.

    Control law: τ = Kp * (q_d - q) + Kd * (q̇_d - q̇)

    Args:
        target_pos: Target joint positions (n_joints,)
        target_vel: Target joint velocities (n_joints,)
        current_pos: Current joint positions (n_joints,)
        current_vel: Current joint velocities (n_joints,)
        kp: Proportional gains (n_joints,)
        kd: Derivative gains (n_joints,)
        max_torque: Maximum torque limits (optional)

    Returns:
        Computed torque command (n_joints,)
    """
    torque = kp * (target_pos - current_pos) + kd * (target_vel - current_vel)

    if max_torque is not None:
        torque = np.clip(torque, -max_torque, max_torque)

    return torque


class PDController:
    """
    PD Controller for trajectory tracking.

    Example:
        gains = PDGains(
            kp=np.array([200, 200, 200, 75, 15, 15]),
            kd=np.array([12.5, 12.5, 12.5, 6.0, 0.31, 0.31]),
            max_torque=np.array([50, 50, 50, 20, 5, 5]),
        )
        controller = PDController(gains)

        torque = controller.compute(target_q, target_qd, current_q, current_qd)
    """

    def __init__(self, gains: PDGains):
        """
        Initialize PD controller.

        Args:
            gains: PDGains configuration
        """
        self.kp = np.asarray(gains.kp)
        self.kd = np.asarray(gains.kd)
        self.max_torque = np.asarray(gains.max_torque) if gains.max_torque is not None else None

    def compute(
        self,
        target_pos: np.ndarray,
        target_vel: np.ndarray,
        current_pos: np.ndarray,
        current_vel: np.ndarray,
    ) -> np.ndarray:
        """
        Compute PD control torque.

        Args:
            target_pos: Target joint positions
            target_vel: Target joint velocities
            current_pos: Current joint positions
            current_vel: Current joint velocities

        Returns:
            Computed torque command
        """
        return compute_pd_torque(
            target_pos, target_vel,
            current_pos, current_vel,
            self.kp, self.kd, self.max_torque
        )
