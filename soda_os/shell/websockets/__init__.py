#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
WebSocket Endpoints
===================

Real-time communication channels:
- state: Robot state streaming (30Hz)
- control: Jogging with deadman switch
- legacy: Compatible with soda_ui frontend
"""

from .state import state_router
from .control import control_router
from .legacy import get_legacy_websocket_handler

__all__ = ["state_router", "control_router", "get_legacy_websocket_handler"]
