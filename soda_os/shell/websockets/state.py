#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
State WebSocket — real-time dual-arm robot state streaming
===========================================================

Protocol (server -> client, ~30 Hz)::

    {
        "type": "dual_robot_state",
        "timestamp": 1234567890.123,
        "arms": {
            "left": {
                "joint_positions":  [...],
                "joint_velocities": [...],
                "ee_position":      [x, y, z],
                "ee_rotation":      [[...], [...], [...]],
                "gripper_position": 0.0      # optional, only if state has it
            },
            "right": { ... same shape ... }
        }
    }

The shape is fixed dict-of-arms — no single-arm fallback path. If an arm
isn't connected or doesn't return a fresh state its entry is omitted so
the client can still see the working arm. ``timestamp`` is the server's
wall clock at send time (use the per-arm ``timestamp`` inside each entry
for the actual hardware sample time).
"""

import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


state_router = APIRouter()


_ARMS = ("left", "right")


def get_state_websocket_handler(app, rate: float = 30.0):
    """Create a WebSocket handler that streams dual-arm state at ``rate`` Hz."""

    async def state_websocket(websocket: WebSocket):
        await websocket.accept()

        dual = getattr(app.state, "dual", None)
        dt = 1.0 / rate

        try:
            while True:
                if dual is not None:
                    arms_msg = {}
                    for arm in _ARMS:
                        robot = getattr(dual, arm, None)
                        if robot is None:
                            continue
                        s = robot.get_state()
                        if s is None:
                            continue
                        entry = {
                            "joint_positions":  s.joint_positions.tolist(),
                            "joint_velocities": s.joint_velocities.tolist(),
                            "ee_position":      s.ee_position.tolist(),
                            "ee_rotation":      s.ee_rotation.tolist(),
                            "timestamp":        s.timestamp,
                        }
                        # 7th joint is the gripper when present.
                        if len(s.joint_positions) > 6:
                            entry["gripper_position"] = float(s.joint_positions[6])
                        arms_msg[arm] = entry

                    if arms_msg:
                        await websocket.send_json({
                            "type": "dual_robot_state",
                            "timestamp": time.time(),
                            "arms": arms_msg,
                        })

                await asyncio.sleep(dt)

        except WebSocketDisconnect:
            pass

        except Exception as e:
            print(f"[State] Error: {e}")

    return state_websocket
