#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Control WebSocket - Jogging with Deadman Switch
================================================

Provides real-time jogging control with safety guarantee:
disconnect = brake

Protocol:
    Client -> Server:
        {"type": "jog_start", "direction": "j1+"}
        {"type": "heartbeat"}
        {"type": "jog_stop"}

    Server -> Client:
        {"type": "jog_ack", "success": true}
        {"type": "jog_state", "is_jogging": true, "direction": "j1+"}
        {"type": "error", "message": "..."}

Safety:
    - Motion stops automatically if no heartbeat for 200ms
    - WebSocket disconnect triggers immediate stop
    - All jog commands require active heartbeat
"""

import asyncio
import time
from typing import Optional, Dict, Any
from enum import Enum

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


# Jog directions
class JogDirection(str, Enum):
    # Joint space
    J1_POS = "j1+"
    J1_NEG = "j1-"
    J2_POS = "j2+"
    J2_NEG = "j2-"
    J3_POS = "j3+"
    J3_NEG = "j3-"
    J4_POS = "j4+"
    J4_NEG = "j4-"
    J5_POS = "j5+"
    J5_NEG = "j5-"
    J6_POS = "j6+"
    J6_NEG = "j6-"
    # Cartesian space
    X_POS = "x+"
    X_NEG = "x-"
    Y_POS = "y+"
    Y_NEG = "y-"
    Z_POS = "z+"
    Z_NEG = "z-"


# Direction to velocity vector mapping
DIRECTION_VECTORS = {
    # Joint directions (rad/s multipliers)
    JogDirection.J1_POS: ([1, 0, 0, 0, 0, 0], "joint"),
    JogDirection.J1_NEG: ([-1, 0, 0, 0, 0, 0], "joint"),
    JogDirection.J2_POS: ([0, 1, 0, 0, 0, 0], "joint"),
    JogDirection.J2_NEG: ([0, -1, 0, 0, 0, 0], "joint"),
    JogDirection.J3_POS: ([0, 0, 1, 0, 0, 0], "joint"),
    JogDirection.J3_NEG: ([0, 0, -1, 0, 0, 0], "joint"),
    JogDirection.J4_POS: ([0, 0, 0, 1, 0, 0], "joint"),
    JogDirection.J4_NEG: ([0, 0, 0, -1, 0, 0], "joint"),
    JogDirection.J5_POS: ([0, 0, 0, 0, 1, 0], "joint"),
    JogDirection.J5_NEG: ([0, 0, 0, 0, -1, 0], "joint"),
    JogDirection.J6_POS: ([0, 0, 0, 0, 0, 1], "joint"),
    JogDirection.J6_NEG: ([0, 0, 0, 0, 0, -1], "joint"),
    # Cartesian directions (m/s multipliers)
    JogDirection.X_POS: ([1, 0, 0, 0, 0, 0], "cartesian"),
    JogDirection.X_NEG: ([-1, 0, 0, 0, 0, 0], "cartesian"),
    JogDirection.Y_POS: ([0, 1, 0, 0, 0, 0], "cartesian"),
    JogDirection.Y_NEG: ([0, -1, 0, 0, 0, 0], "cartesian"),
    JogDirection.Z_POS: ([0, 0, 1, 0, 0, 0], "cartesian"),
    JogDirection.Z_NEG: ([0, 0, -1, 0, 0, 0], "cartesian"),
}


class JogSession:
    """
    Jogging session with deadman switch.

    Each WebSocket connection has one JogSession.
    Motion continues only while heartbeat is received.
    """

    def __init__(
        self,
        robot_service,
        websocket: WebSocket,
        joint_speed: float = 0.5,       # rad/s
        cartesian_speed: float = 0.05,  # m/s
        heartbeat_timeout: float = 0.2,  # seconds
        control_rate: float = 100.0,     # Hz
    ):
        self.robot = robot_service
        self.websocket = websocket

        # Config
        self.joint_speed = joint_speed
        self.cartesian_speed = cartesian_speed
        self.heartbeat_timeout = heartbeat_timeout
        self.control_rate = control_rate

        # State
        self.is_jogging = False
        self.direction: Optional[str] = None
        self.mode: Optional[str] = None  # "joint" or "cartesian"
        self.velocity_vector: Optional[list] = None
        self.last_heartbeat: float = 0.0

        # Tasks
        self._jog_task: Optional[asyncio.Task] = None
        self._deadman_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start_jog(self, direction: str) -> bool:
        """Start jogging in specified direction."""
        # Stop any existing jog first
        await self.stop_jog()

        # Parse direction
        try:
            jog_dir = JogDirection(direction.lower())
        except ValueError:
            await self._send_error(f"Invalid direction: {direction}")
            return False

        if jog_dir not in DIRECTION_VECTORS:
            await self._send_error(f"Unknown direction: {direction}")
            return False

        self.velocity_vector, self.mode = DIRECTION_VECTORS[jog_dir]
        self.direction = direction
        self.is_jogging = True
        self.last_heartbeat = time.time()
        self._stop_event.clear()

        # Start background tasks
        self._deadman_task = asyncio.create_task(self._deadman_loop())
        self._jog_task = asyncio.create_task(self._jog_loop())

        await self._send_state()
        return True

    def heartbeat(self) -> bool:
        """Update heartbeat timestamp."""
        if not self.is_jogging:
            return False
        self.last_heartbeat = time.time()
        return True

    async def stop_jog(self) -> None:
        """Stop jogging immediately."""
        if not self.is_jogging:
            return

        self._stop_event.set()

        # Cancel tasks
        for task in [self._jog_task, self._deadman_task]:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._jog_task = None
        self._deadman_task = None

        # Stop robot
        if self.robot is not None:
            self.robot.stop()

        # Clear state
        self.is_jogging = False
        self.direction = None
        self.mode = None
        self.velocity_vector = None

        await self._send_state()

    async def _deadman_loop(self) -> None:
        """Monitor heartbeat and stop if timeout."""
        check_interval = self.heartbeat_timeout / 4

        while not self._stop_event.is_set():
            await asyncio.sleep(check_interval)

            elapsed = time.time() - self.last_heartbeat
            if elapsed > self.heartbeat_timeout:
                print(f"[Deadman] Heartbeat timeout: {elapsed:.3f}s")
                await self._send_error(f"Heartbeat timeout ({elapsed:.3f}s)")
                await self.stop_jog()
                break

    async def _jog_loop(self) -> None:
        """Send jog commands at control rate."""
        import numpy as np

        dt = 1.0 / self.control_rate

        while not self._stop_event.is_set() and self.is_jogging:
            try:
                if self.robot is None or not self.robot.is_connected:
                    await asyncio.sleep(dt)
                    continue

                # Get current position
                current_q = self.robot.get_joint_positions()
                if current_q is None:
                    await asyncio.sleep(dt)
                    continue

                if self.mode == "joint":
                    await self._jog_joint(current_q, dt)
                elif self.mode == "cartesian":
                    await self._jog_cartesian(current_q, dt)

                await asyncio.sleep(dt)

            except Exception as e:
                print(f"[Jog] Error: {e}")
                await self._send_error(str(e))
                await self.stop_jog()
                break

    async def _jog_joint(self, current_q, dt: float) -> None:
        """Execute joint space jog step."""
        import numpy as np

        # Compute velocity
        velocity = np.array(self.velocity_vector) * self.joint_speed

        # Compute target position
        arm_q = np.array(current_q[:6])
        target_q = arm_q + velocity * dt

        # Apply joint limits
        limits = self.robot.get_joint_limits()
        if limits is not None:
            lower, upper = limits
            margin = 0.05  # 3 degrees
            target_q = np.clip(target_q, lower + margin, upper - margin)

        # Send command
        if len(current_q) > 6:
            full_cmd = np.concatenate([target_q, current_q[6:]])
        else:
            full_cmd = target_q

        if hasattr(self.robot, '_client') and self.robot._client is not None:
            # Driver expects dict-of-arms; route to this session's arm.
            self.robot._client.set_cmds({getattr(self.robot, '_arm_name', 'left'): full_cmd})

    async def _jog_cartesian(self, current_q, dt: float) -> None:
        """Execute Cartesian space jog step."""
        import numpy as np

        if self.robot.kinematics is None:
            return

        # Get current EE position
        state = self.robot.get_state()
        if state is None:
            return

        current_pos = state.ee_position

        # Compute position delta
        direction = np.array(self.velocity_vector[:3])
        delta_pos = direction * self.cartesian_speed * dt
        target_pos = current_pos + delta_pos

        # Solve IK
        result = self.robot.kinematics.inverse(
            target_pos,
            current_q[:6],
            mode="position",
        )

        if not result.success:
            return  # Skip this step

        target_q = result.joint_positions

        # Apply joint limits
        limits = self.robot.get_joint_limits()
        if limits is not None:
            lower, upper = limits
            margin = 0.05
            target_q = np.clip(target_q, lower + margin, upper - margin)

        # Send command
        if len(current_q) > 6:
            full_cmd = np.concatenate([target_q, current_q[6:]])
        else:
            full_cmd = target_q

        if hasattr(self.robot, '_client') and self.robot._client is not None:
            # Driver expects dict-of-arms; route to this session's arm.
            self.robot._client.set_cmds({getattr(self.robot, '_arm_name', 'left'): full_cmd})

    async def _send_state(self) -> None:
        """Send current jog state to client."""
        try:
            await self.websocket.send_json({
                "type": "jog_state",
                "is_jogging": self.is_jogging,
                "direction": self.direction,
                "mode": self.mode,
            })
        except Exception:
            pass

    async def _send_error(self, message: str) -> None:
        """Send error to client."""
        try:
            await self.websocket.send_json({
                "type": "error",
                "message": message,
            })
        except Exception:
            pass


# Router for control WebSocket
control_router = APIRouter()


def get_control_websocket_handler(app):
    """Create WebSocket handler with access to app state."""

    async def control_websocket(websocket: WebSocket):
        """
        WebSocket endpoint for jogging control.

        Safety: Motion stops when:
        - Client sends jog_stop
        - No heartbeat for 200ms
        - WebSocket disconnects
        """
        await websocket.accept()

        # Get robot service from app state
        robot = getattr(app.state, 'robot', None)

        # Get config
        config = getattr(app.state, 'config', None)
        jog_config = {}
        if config is not None:
            jog_config = config.get("jogging", {})

        # Create session
        session = JogSession(
            robot_service=robot,
            websocket=websocket,
            joint_speed=jog_config.get("joint_speed", 0.5),
            cartesian_speed=jog_config.get("cartesian_speed", 0.05),
            heartbeat_timeout=jog_config.get("heartbeat_timeout", 0.2),
            control_rate=jog_config.get("control_rate", 100.0),
        )

        try:
            # Send initial state
            await session._send_state()

            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "jog_start":
                    direction = data.get("direction", "")
                    success = await session.start_jog(direction)
                    await websocket.send_json({
                        "type": "jog_ack",
                        "success": success,
                        "direction": direction if success else None,
                    })

                elif msg_type == "heartbeat":
                    success = session.heartbeat()
                    # No response needed for heartbeat (low latency)

                elif msg_type == "jog_stop":
                    await session.stop_jog()
                    await websocket.send_json({
                        "type": "jog_ack",
                        "success": True,
                        "direction": None,
                    })

                elif msg_type == "get_state":
                    await session._send_state()

                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    })

        except WebSocketDisconnect:
            print("[Control] WebSocket disconnected, stopping jog")
            await session.stop_jog()

        except Exception as e:
            print(f"[Control] Error: {e}")
            await session.stop_jog()

    return control_websocket
