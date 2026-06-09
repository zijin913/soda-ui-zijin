#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
SODA OS Shell Layer
===================

The Shell is the user-facing layer of SODA OS.
Provides REST API, WebSocket, and static file serving for the frontend.

Usage:
    # Start Shell server
    python -m soda_os.shell.server

    # Or programmatically
    from soda_os.shell import create_app
    app = create_app(config, robot_service, camera_service)

Endpoints:
    REST API:
        GET  /health              - Health check
        GET  /robot/state         - Get robot state
        POST /robot/move/position - Move to position
        POST /robot/move/joints   - Move to joints
        GET  /camera/rgb          - Get RGB image
        ...

    WebSocket:
        /ws/state   - Real-time robot state (30Hz)
        /ws/control - Jogging control with deadman switch
"""

from .server import create_app, app

__all__ = ["create_app", "app"]
