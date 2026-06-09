#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Core Layer
==========

Fundamental robotics computations (stateless math/physics):
- kinematics: FK/IK using Pinocchio + analytic solver
- dynamics: Robot dynamics and gravity compensation
- planning: Trajectory generation (minimum jerk, trapezoidal)
- control: PD control algorithms
- transforms: Coordinate frame transformations
- calibration: Hand-eye calibration data management
- analytic_ik: Geometric closed-form IK solver
"""

from .kinematics import Kinematics, IKResult
from .transforms import Transforms
from .calibration import CalibrationManager
from .dynamics import Dynamics
from .planning import TrajectoryGenerator, MotionPrimitives, Trajectory
from .control import compute_pd_torque, PDGains

# Analytic IK (optional, used internally by Kinematics)
try:
    from .analytic_ik import AnalyticIKSolver, create_analytic_solver
except ImportError:
    AnalyticIKSolver = None
    create_analytic_solver = None

__all__ = [
    "Kinematics", "IKResult",
    "Transforms",
    "CalibrationManager",
    "Dynamics",
    "TrajectoryGenerator", "MotionPrimitives", "Trajectory",
    "compute_pd_torque", "PDGains",
    "AnalyticIKSolver", "create_analytic_solver",
]
