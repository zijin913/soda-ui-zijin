#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
API Routes
==========

FastAPI route modules.
"""

from .robot import router as robot_router
from .camera import router as camera_router

__all__ = ["robot_router", "camera_router"]
