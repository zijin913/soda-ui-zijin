#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Legacy WebSocket — dual-arm, compatible with soda_ui frontend
=============================================================

Provides /ws endpoint using MessagePack framing. The shell backend is
dual-arm only; the message always carries an ``arms`` dict.

Protocol — Server -> Client (binary):
    Each frame is ``4-byte little-endian length || msgpack(payload)``.

    Payload shape::

        {
            "arms": {
                "left":  {"video"?: bytes, "joints": [...], "gripper_distance"?: float},
                "right": {"video"?: bytes, "joints": [...], "gripper_distance"?: float}
            },
            "side_video"?:  bytes,   # ~10 Hz, when a side camera is wired
            "pointcloud"?:  list     # ~5 Hz, merged xyzrgb (left + right (+ side))
        }

    Wrist video alternates between the two arms each frame so each arm
    gets ~fps/2; that halves bandwidth vs sending both every frame.

Protocol — Client -> Server (JSON text):
    {"type": "joint_command", "side": "left"|"right", "joint_name": "joint_1",
     "angle": 1.5}                                  # absolute target
    {"type": "joint_command", "side": "left", "joint_name": "joint_2",
     "delta_angle": 0.05}                           # incremental
    {"type": "gripper_set", "side": "right", "distance": 0.05}

``side`` is required — there is no single-arm fallback.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from typing import Dict, Optional

import cv2
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

try:
    import msgpack
    HAS_MSGPACK = True
except ImportError:
    HAS_MSGPACK = False
    print("[Legacy WS] Warning: msgpack not installed, install with: pip install msgpack")


# Joint names for firefly_y6 + GR100. Same names per arm — the outer
# arms.{side} key in the payload disambiguates left vs right.
JOINT_NAMES = ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6", "gripper_left_joint_1"]
_ARMS = ("left", "right")

# Gripper config: GR100 lobster-claw fully-closed at 0.67 rad — matches the real
# robot (launchers/configs/*_arm_cfg.json :: gripper_max_position = 0.67).
# Used to convert finger-tip distance ⇆ joint angle for the frontend slider.
GRIP_MAX_DIST = 0.100   # m (100 mm fully open)
GRIP_MIN_DIST = 0.010   # m (10 mm fully closed)
GRIP_CLOSE_ANGLE = 0.67  # rad, GR100 fully-closed (== real gripper_max_position)


def _get_grip_close_angle(app) -> float:
    """Allow config to override the default GR100 close angle."""
    try:
        cfg = getattr(app.state, "config", None)
        if cfg is not None:
            return float(
                cfg.get("robot.gripper.close_position", GRIP_CLOSE_ANGLE)
            )
    except Exception:
        pass
    return GRIP_CLOSE_ANGLE


def get_legacy_websocket_handler(app, fps: float = 30.0):
    """Create the /ws handler that streams dual-arm telemetry to soda_ui."""

    async def legacy_websocket(websocket: WebSocket):
        await websocket.accept()
        print("[Legacy WS] Client connected")

        if not HAS_MSGPACK:
            print("[Legacy WS] Error: msgpack not available")
            await websocket.close()
            return

        dual = getattr(app.state, "dual", None)
        cameras: Dict = getattr(app.state, "cameras", {}) or {}
        if dual is None:
            print("[Legacy WS] Error: app.state.dual not initialised")
            await websocket.close()
            return

        dt = 1.0 / fps
        frame_count = 0
        grip_close = _get_grip_close_angle(app)

        # ``right_base_in_left`` is the translation from the right-arm base
        # frame origin to the left-arm base frame origin, expressed in the
        # left base frame. Default uses the firefly_y6 sim spacing (0.448 m
        # between bases along -Y). Override via app.state.right_base_in_left.
        rbl_raw = getattr(app.state, "right_base_in_left", None)
        if rbl_raw is None:
            rbl_raw = [0.0, -0.448, 0.0]
        right_base_in_left = np.asarray(rbl_raw, dtype=np.float32).reshape(3)

        # Per-arm point cloud cache: when a given arm's cloud fails to
        # generate this cycle (depth/rgb temporarily None or no valid
        # pixels), reuse the previous cycle's cloud so the merged cloud
        # sent to the frontend always contains both arms' coverage. Without
        # this the rendered cloud "size" oscillates between left-only,
        # right-only and both, which the user perceives as flicker.
        cloud_cache: Dict[str, np.ndarray] = {}

        try:
            while True:
                start_time = time.time()
                frame_count += 1

                # While teleop streams OR replay is playing, this broadcast must
                # NOT hog the shared event loop / ZMQ client — it would delay the
                # set_cmds those paths issue (jerky teleop; replay runs slow, a
                # 5 s clip taking 10+ s). So shed the heavy per-frame work
                # (camera JPEG + point cloud); lightweight joints still flow so
                # the 3D arms keep moving in the UI.
                teleop_active = bool(getattr(app.state, "teleop_active", False))
                replay_active = (getattr(app.state, "current_mode", "realtime") == "replay")
                shed = teleop_active or replay_active

                # 1) Pull any client messages without blocking.
                try:
                    msg = await asyncio.wait_for(
                        websocket.receive_text(), timeout=0.001
                    )
                    await _handle_command(msg, dual, app)
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    pass

                # 2) Build per-arm payload.
                video_arm_idx = frame_count % len(_ARMS)
                arms_payload = {}
                for idx, arm in enumerate(_ARMS):
                    arm_data = {}
                    robot = getattr(dual, arm)
                    state = robot.get_state()

                    # Wrist video — alternate so each arm gets ~fps/2 Hz.
                    # Skipped while teleop streams (JPEG encode is heavy).
                    if idx == video_arm_idx and not shed:
                        cam = cameras.get(arm)
                        if cam is not None:
                            try:
                                rgb = cam.get_rgb()
                                if rgb is not None:
                                    _, buf = cv2.imencode(
                                        ".jpg", rgb,
                                        [int(cv2.IMWRITE_JPEG_QUALITY), 50],
                                    )
                                    arm_data["video"] = buf.tobytes()
                            except Exception:
                                pass

                    # Joints + gripper distance for both arms every frame.
                    if state is not None:
                        arm_data["joints"] = _state_to_joint_list(state)
                        if len(state.joint_positions) > 6:
                            grip_angle = float(state.joint_positions[6])
                            ratio = max(0.0, min(1.0, grip_angle / grip_close))
                            arm_data["gripper_distance"] = (
                                GRIP_MAX_DIST - ratio * (GRIP_MAX_DIST - GRIP_MIN_DIST)
                            )
                    arms_payload[arm] = arm_data

                # `dual_mode: True` is a hint to the soda-ui frontend so its
                # legacy decoder picks the dual-arm parsing path (`arms`
                # presence is the actual signal; the flag is just a marker).
                msg_data = {"dual_mode": True, "arms": arms_payload}

                # 3) Side camera at ~fps/3 if present in cameras dict.
                side_cam = cameras.get("side")
                if side_cam is not None and not shed and frame_count % 3 == 0:
                    try:
                        rgb = side_cam.get_rgb()
                        if rgb is not None:
                            _, buf = cv2.imencode(
                                ".jpg", rgb,
                                [int(cv2.IMWRITE_JPEG_QUALITY), 50],
                            )
                            msg_data["side_video"] = buf.tobytes()
                    except Exception:
                        pass

                # 4) Merged point cloud at ~5 Hz (every 6 frames @ 30 fps).
                # Skipped while teleop streams (vstack + .tolist() of ~12k
                # points + msgpack is the single heaviest event-loop blocker).
                merged_cloud_np = None
                if not shed and frame_count % 6 == 0:
                    try:
                        clouds = []
                        for arm in _ARMS:
                            offset = right_base_in_left if arm == "right" else None
                            c = _arm_pointcloud(dual, cameras, arm, base_offset=offset)
                            if c is not None:
                                cloud_cache[arm] = c
                                clouds.append(c)
                            elif arm in cloud_cache:
                                # Fresh cloud failed this cycle — reuse last.
                                clouds.append(cloud_cache[arm])
                        side_c = _side_pointcloud(cameras, app)
                        if side_c is not None:
                            cloud_cache["side"] = side_c
                            clouds.append(side_c)
                        elif "side" in cloud_cache:
                            clouds.append(cloud_cache["side"])
                        if clouds:
                            merged_cloud_np = np.vstack(clouds)
                            msg_data["pointcloud"] = merged_cloud_np.tolist()
                    except Exception:
                        pass

                # 4b) Recording lives in teleop (scripts/teleop_quest.py →
                # TrajectoryRecorder), launched via /api/teleop/start. The
                # backend no longer records from this WS loop.

                # 5) Send.
                try:
                    packed = msgpack.packb(msg_data, use_bin_type=True)
                    header = struct.pack("<I", len(packed))
                    await websocket.send_bytes(header + packed)
                except Exception:
                    pass

                # Low rate while teleop streams so the event loop stays free
                # for command forwarding; full rate otherwise.
                eff_dt = 0.1 if teleop_active else dt
                elapsed = time.time() - start_time
                await asyncio.sleep(max(0.0, eff_dt - elapsed))

        except WebSocketDisconnect:
            print("[Legacy WS] Client disconnected")
        except Exception as e:
            print(f"[Legacy WS] Error: {e}")

    return legacy_websocket


# -------------------- point-cloud helpers --------------------

def _arm_pointcloud(dual, cameras: Dict, arm: str, base_offset=None):
    """Return per-arm xyzrgb cloud expressed in the left-arm base frame."""
    robot = getattr(dual, arm, None)
    cam = cameras.get(arm)
    if robot is None or cam is None:
        return None
    T_cam2gripper = robot.transforms.T_cam2gripper if robot.transforms else None
    state = robot.get_state()
    if T_cam2gripper is None or state is None:
        return None
    T_gripper2base = robot.kinematics.forward(state.joint_positions[:6])
    res = cam.get_point_cloud_in_base_frame(
        T_gripper2base, T_cam2gripper, downsample=8,
    )
    if res is None:
        return None
    pts, colors = res
    if base_offset is not None:
        pts = pts + base_offset
    return np.hstack([pts, colors]).astype(np.float32)


def _side_pointcloud(cameras: Dict, app):
    """Side camera cloud expressed in the left-arm base frame.

    Requires ``app.state.side_calibration["T_cam2base"]`` (4x4 numpy).
    Returns None when no side cam or no calibration available.
    """
    side_cam = cameras.get("side")
    side_calib = getattr(app.state, "side_calibration", None)
    if side_cam is None or side_calib is None:
        return None
    T_cam2base = side_calib.get("T_cam2base") if isinstance(side_calib, dict) else None
    if T_cam2base is None:
        return None
    T_cam2base = np.asarray(T_cam2base, dtype=np.float64).reshape(4, 4)
    res = side_cam.get_point_cloud_in_base_frame(
        np.eye(4), T_cam2base, downsample=8,
    )
    if res is None:
        return None
    pts, colors = res
    return np.hstack([pts, colors]).astype(np.float32)


# -------------------- inbound command handler --------------------

def _gripper_distance_to_angle(distance_m: float, max_angle: float) -> float:
    """Convert finger-tip distance (m) to gripper joint angle (rad)."""
    dist = max(GRIP_MIN_DIST, min(GRIP_MAX_DIST, distance_m))
    return (GRIP_MAX_DIST - dist) / (GRIP_MAX_DIST - GRIP_MIN_DIST) * max_angle


# Per-arm last commanded joint vector so gripper-only / joint-only commands
# don't accidentally let the other joints drift.
_last_cmd_q: Dict[str, Optional[np.ndarray]] = {"left": None, "right": None}


async def _handle_command(msg: str, dual, app) -> None:
    """Apply an incoming joint/gripper command to the specified arm."""
    try:
        data = json.loads(msg)
        cmd_type = data.get("type")
        side = data.get("side")
        if side not in _ARMS:
            return
        robot = getattr(dual, side)
        if robot is None:
            return
        last_q = _last_cmd_q[side]

        if cmd_type == "joint_command":
            joint_name = data.get("joint_name")
            angle = data.get("angle")
            delta_angle = data.get("delta_angle")
            if joint_name not in JOINT_NAMES:
                return
            joint_idx = JOINT_NAMES.index(joint_name)
            current_q = robot.get_joint_positions()
            if current_q is None:
                return
            target_q = last_q.copy() if last_q is not None else current_q.copy()
            if delta_angle is not None:
                target_q[joint_idx] += float(delta_angle)
            elif angle is not None:
                target_q[joint_idx] = float(angle)
            else:
                return
            _last_cmd_q[side] = target_q.copy()
            if hasattr(robot, "_client") and robot._client is not None:
                # Driver expects dict-of-arms.
                robot._client.set_cmds({side: target_q})

        elif cmd_type == "gripper_set":
            distance = data.get("distance")
            if distance is None:
                return
            grip_angle = _gripper_distance_to_angle(
                float(distance), max_angle=_get_grip_close_angle(app),
            )
            current_q = robot.get_joint_positions()
            if current_q is None or len(current_q) <= 6:
                return
            target_q = last_q.copy() if last_q is not None else current_q.copy()
            target_q[6] = grip_angle
            _last_cmd_q[side] = target_q.copy()
            if hasattr(robot, "_client") and robot._client is not None:
                robot._client.set_cmds({side: target_q})

    except json.JSONDecodeError:
        pass
    except Exception as e:
        print(f"[Legacy WS] Command error: {e}")


def _state_to_joint_list(state) -> list:
    """Convert RobotState → list of joint dicts for soda_ui."""
    joints = []
    n_joints = min(len(state.joint_positions), len(JOINT_NAMES))
    for i in range(n_joints):
        joints.append({
            "id": i,
            "name": JOINT_NAMES[i],
            "angle": float(state.joint_positions[i]),
            "velocity": float(state.joint_velocities[i]) if i < len(state.joint_velocities) else 0.0,
            "torque":   float(state.joint_torques[i])    if i < len(state.joint_torques)    else 0.0,
        })
    return joints
