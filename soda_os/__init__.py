#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
SODA OS - Robot Operating System for HexArm
============================================

Layered architecture:
- api/        : REST/WebSocket API for frontend
- services/   : High-level robot services
- core/       : Kinematics, transforms, calibration
- algorithms/ : Motion planning, perception
- config/     : Unified configuration management

Driver layer: hex_zmq_servers (external)
"""

__version__ = "0.1.0"
__author__ = "SODA Team"

from .config import ConfigManager
from .core import Kinematics, Transforms, CalibrationManager
from .services import RobotService, CameraService

__all__ = [
    "ConfigManager",
    "Kinematics",
    "Transforms",
    "CalibrationManager",
    "RobotService",
    "CameraService",
]
