#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
SODA OS Shell Server
====================

FastAPI application serving as the Shell layer for SODA OS.
Provides REST API and WebSocket endpoints for robot control.

Architecture:
    Shell (this server) -> Services -> Core -> Drivers -> Hardware

Usage:
    # Start server
    python -m soda_os.shell.server

    # Or with uvicorn
    uvicorn soda_os.shell.server:app --host 0.0.0.0 --port 8000

Endpoints:
    REST:
        /health           - Health check
        /robot/*          - Robot control API
        /camera/*         - Camera API
        /camera/stream    - MJPEG video stream

    WebSocket:
        /ws/state         - Robot state streaming (30Hz)
        /ws/control       - Jogging with deadman switch
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import numpy as np

from fastapi import Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fastapi.responses import JSONResponse

from .routes import robot_router, camera_router
from .websockets.state import get_state_websocket_handler
from .websockets.control import get_control_websocket_handler
from .websockets.legacy import get_legacy_websocket_handler
from .websockets.teleop import get_teleop_websocket_handler

from ..drivers import DriverFactory
from ..services import (
    CameraService,
    DualArmRobotService,
    RobotService,
)
from ..config import ConfigManager


# ---------------------------------------------------------------------------
# Replay playback driver
# ---------------------------------------------------------------------------
# A single task owns replay playback: advances the frame at a fixed rate and
# streams joint commands to both arms via the SAME shared client UI jog and
# teleop use (last-writer-wins, single seq). The arm physically moves, so the
# live /ws state stream shows the motion — the frontend just renders live.

def _drive_replay_arms(dual, left_q, right_q) -> None:
    """Send one replay frame's joints to both arms (blocking ZMQ — invoked
    via asyncio.to_thread so it never blocks the event loop)."""
    for side, q in (("left", left_q), ("right", right_q)):
        if q is None:
            continue
        robot = getattr(dual, side, None)
        client = getattr(robot, "_client", None) if robot is not None else None
        if client is not None:
            try:
                client.set_cmds({side: q})
            except Exception as e:
                print(f"[replay] set_cmds {side} failed: {e}")


async def _run_replay_playback(app, fps: float = 30.0) -> None:
    """Advance the loaded replay at ``fps`` and command both arms each frame.
    Stops at the last frame, on pause, or on mode/replay change."""
    replay = getattr(app.state, "replay", None)
    dual = getattr(app.state, "dual", None)
    if replay is None or dual is None:
        return
    # Honour the loaded replay's own fps (it resamples to its target fps).
    fps = float(getattr(replay, "fps", fps) or fps)
    dt = 1.0 / fps
    print(f"[replay] ▶ playback task started at frame {replay.current_frame_idx} "
          f"({fps:.0f}Hz)")
    try:
        while (getattr(app.state, "current_mode", "realtime") == "replay"
               and getattr(app.state, "replay", None) is replay
               and replay.is_playing):
            t0 = time.perf_counter()
            idx = replay.current_frame_idx
            left_q, right_q = replay.get_frame_joints(idx)
            if left_q is not None:
                await asyncio.to_thread(_drive_replay_arms, dual, left_q, right_q)
            nxt = idx + 1
            if nxt >= replay.total_frames:
                replay.is_playing = False
                break
            replay.current_frame_idx = nxt
            # Subtract the time already spent driving so the playback holds the
            # recorded fps (was sleeping a full dt AFTER driving → ran slow).
            await asyncio.sleep(max(0.0, dt - (time.perf_counter() - t0)))
    except asyncio.CancelledError:
        pass
    finally:
        print(f"[replay] ⏹ playback task stopped at frame {replay.current_frame_idx}")


def _cancel_replay_task(app) -> None:
    task = getattr(app.state, "replay_task", None)
    if task is not None and not task.done():
        task.cancel()
    app.state.replay_task = None


# Request model for joint command (legacy single-joint endpoint).
# ``arm`` selects which arm to actuate (default left for backward compat).
class JointCommandRequest(BaseModel):
    joint_name: str
    angle: float
    arm: str = "left"


def create_app(
    config: Optional[ConfigManager] = None,
    dual: Optional[DualArmRobotService] = None,
    cameras: Optional[Dict[str, CameraService]] = None,
) -> FastAPI:
    """
    Create FastAPI application (dual-arm only).

    Args:
        config:   Configuration manager
        dual:     Pre-built DualArmRobotService (one per-arm RobotService each)
        cameras:  Pre-built per-arm CameraService dict, e.g.
                  ``{"left": CameraService(...), "right": CameraService(...)}``
                  When omitted both default to the shared dual-arm driver.

    Returns:
        FastAPI app instance
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ==================== Startup ====================
        print("=" * 50)
        print("SODA OS Shell Starting (dual-arm)...")
        print("=" * 50)

        nonlocal dual, cameras

        # Load config
        if config is None:
            cfg = ConfigManager()
        else:
            cfg = config

        # ---- Dual-arm robot service ----
        if dual is None:
            robot_config = dict(cfg.get_namespace("robot") or {})
            # ConfigManager stores robot.network at top level; the dual-arm
            # service expects ``mode`` (sim/real). Default to sim because the
            # shell is most often run alongside the MuJoCo sim launcher.
            # Tolerate older configs that only set the per-namespace key.
            _mode = cfg.get("mode") or cfg.get("robot.mode") or "sim"
            robot_config.setdefault("mode", _mode)
            # Per-arm calibration JSON discovery — look under
            # hand_eye_calibration/results/<arm>/ first, fall back to the
            # flat dir for legacy single-arm calibrations.
            calibration_paths = cfg.find_calibration_files()
            # If neither arm has its own file, fall back to the flat
            # search so a legacy single-arm calibration JSON still loads.
            if not any(calibration_paths.values()):
                shared = cfg.find_calibration_file()
                if shared:
                    calibration_paths = {"left": shared, "right": shared}
                else:
                    calibration_paths = None
            else:
                # Backfill the missing arm with the other arm's file so
                # the dual service has *something* on both sides during
                # incremental calibration rollout.
                if calibration_paths["left"] is None and calibration_paths["right"]:
                    calibration_paths["left"] = calibration_paths["right"]
                if calibration_paths["right"] is None and calibration_paths["left"]:
                    calibration_paths["right"] = calibration_paths["left"]
            dual = DualArmRobotService.from_config(
                config=robot_config,
                calibration_paths=calibration_paths,
            )

        # ---- Per-arm cameras ----
        if cameras is None:
            cameras = {}
            # Both per-arm CameraService instances share the camera driver
            # so we only spin up one ZMQ session per camera.
            mode = (cfg.get("mode") or cfg.get("camera.mode") or "sim")
            cam_factory = DriverFactory(
                mode=mode,
                config={
                    "sim":    cfg.get_namespace("sim")    or {},
                    "robot":  cfg.get_namespace("robot")  or {},
                    "camera": cfg.get_namespace("camera") or {},
                },
            )
            shared_cam_driver = cam_factory.create_camera_driver()
            cameras = {
                "left":  CameraService(camera_client=shared_cam_driver, cam_name="left"),
                "right": CameraService(camera_client=shared_cam_driver, cam_name="right"),
                # Side cam is optional — the underlying driver returns it
                # under the "side" key when available (sim third-person /
                # real side RealSense). If no side feed exists this service
                # just stays "connected=True" but get_rgb/get_depth → None.
                "side":  CameraService(camera_client=shared_cam_driver, cam_name="side"),
            }

        # Inject into route modules
        import soda_os.shell.routes.robot as robot_routes
        import soda_os.shell.routes.camera as camera_routes

        robot_routes._dual_service = dual
        camera_routes._cameras = cameras
        camera_routes._dual_service = dual

        # Store in app state (for WebSocket handlers + legacy /api/joint/set).
        app.state.dual = dual
        app.state.cameras = cameras
        app.state.config = cfg
        # Backward-compat shims: legacy code that grabbed app.state.robot or
        # app.state.camera still works; both now point at the LEFT arm.
        app.state.robot = dual.left
        app.state.camera = cameras["left"]

        # Side camera extrinsics — T_cam2base in the LEFT arm's base frame.
        # Sourced from the canonical pipeline output at
        # hand_eye_calibration/results/dual/side.json (produced by
        # scripts/calibrate_camera.py --camera side). Without this the
        # side cam's WS pointcloud branch silently no-ops.
        side_calib_path = calibration_paths.get("side") if isinstance(calibration_paths, dict) else None
        if not side_calib_path:
            side_calib_path = cfg.find_calibration_file("side")
        if side_calib_path:
            try:
                from soda_os.core.calibration import CalibrationManager
                _side_mgr = CalibrationManager()
                _side_mgr.load_side_camera(side_calib_path)
                app.state.side_calibration = {"T_cam2base": _side_mgr.T_cam2base}
                print(f"[Shell] Loaded side calibration: {side_calib_path}")
            except Exception as e:
                print(f"[Shell] Side calibration load failed ({e}); side pointcloud disabled")
                app.state.side_calibration = None
        else:
            print("[Shell] No side calibration found; side pointcloud disabled")
            app.state.side_calibration = None

        # Connect to hardware
        print("[Shell] Connecting to dual-arm robot ...")
        if dual.connect():
            print("[Shell] Both arms connected")
        else:
            print("[Shell] Dual-arm connect failed (will retry on demand)")

        print("[Shell] Connecting to cameras ...")
        for arm, cam in cameras.items():
            if cam.connect():
                print(f"[Shell]   {arm} camera connected")
            else:
                print(f"[Shell]   {arm} camera connect failed")

        print("=" * 50)
        print("SODA OS Shell Ready (dual-arm)")
        print("  REST API:  http://localhost:8000/docs")
        print("  WebSocket: ws://localhost:8000/ws/state")
        print("  WebSocket: ws://localhost:8000/ws/control")
        print("=" * 50)

        yield

        # ==================== Shutdown ====================
        print("\nShutting down SODA OS Shell...")
        if dual:
            dual.disconnect()
        if cameras:
            for cam in cameras.values():
                cam.disconnect()
        print("SODA OS Shell stopped")

    app = FastAPI(
        title="SODA OS Shell",
        description="Robot Operating System API for HexArm",
        version="0.2.0",
        lifespan=lifespan,
    )

    # CORS middleware for frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ==================== REST Routes ====================
    app.include_router(robot_router)
    app.include_router(camera_router)

    # ==================== WebSocket Endpoints ====================

    # State streaming (30Hz)
    @app.websocket("/ws/state")
    async def state_websocket(websocket: WebSocket):
        """Real-time robot state streaming."""
        handler = get_state_websocket_handler(app, rate=30.0)
        await handler(websocket)

    # Jogging control with deadman switch
    @app.websocket("/ws/control")
    async def control_websocket(websocket: WebSocket):
        """Jogging control with deadman switch (disconnect = brake)."""
        handler = get_control_websocket_handler(app)
        await handler(websocket)

    # High-rate dual-arm joint-target ingestion (teleop streams here).
    @app.websocket("/ws/teleop")
    async def teleop_websocket(websocket: WebSocket):
        """Stream {left:[7], right:[7]} joint targets → single shared client."""
        handler = get_teleop_websocket_handler(app)
        await handler(websocket)

    # ==================== Legacy Compatibility (soda_ui) ====================

    # Legacy WebSocket (compatible with soda_server protocol)
    @app.websocket("/ws")
    async def legacy_websocket(websocket: WebSocket):
        """
        Legacy WebSocket for soda_ui frontend compatibility.

        Protocol:
            Server sends: 0x01+JPEG (binary), JSON states (text)
            Client sends: {"type":"joint_command","joint_name":"joint_1","angle":1.5}
        """
        handler = get_legacy_websocket_handler(app, fps=30.0)
        await handler(websocket)

    # URDF endpoint — dual-arm shape consumed by RobotViewport.vue.
    @app.get("/urdf")
    async def get_urdf(request: Request):
        """Return per-arm URDF + base offset for 3D visualization.

        The shell is dual-arm only, so we return the same single-arm URDF
        for both sides plus the world-frame offset between the two arm
        bases. The frontend's URDFLoader instantiates the URDF twice and
        places each at the given ``position`` (in the left-arm base frame).

        ``[0, -0.448, 0]`` matches the firefly_y6 sim scene's arm spacing
        (left at world Y=+0.224, right at Y=-0.224 → right base is at
        Y=-0.448 in left base frame). Override via env / config if your
        real-hardware mounting differs.
        """
        base_url = str(request.base_url).rstrip("/")
        urdf_url = f"{base_url}/assets/firefly_y6_gr100/firefly_y6_gr100.urdf"
        return {
            "dual_mode": True,
            "left":  {"url": urdf_url, "position": [0.0,  0.0,   0.0]},
            "right": {"url": urdf_url, "position": [0.0, -0.448, 0.0]},
        }

    # Joint command endpoint (POST) — single-joint legacy API.
    # ``arm`` field selects which arm; defaults to "left".
    @app.post("/api/joint/set")
    async def set_joint(cmd: JointCommandRequest):
        """Set one joint on one arm (legacy single-joint API)."""
        dual = getattr(app.state, "dual", None)
        if dual is None or not dual.is_connected:
            return {"error": "Dual robot service not connected"}

        if cmd.arm not in ("left", "right"):
            return {"error": f"Invalid arm: {cmd.arm!r} (expected 'left' or 'right')"}
        robot = getattr(dual, cmd.arm)

        joint_names = ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6"]
        if cmd.joint_name not in joint_names:
            return {"error": f"Invalid joint name: {cmd.joint_name}"}

        try:
            joint_idx = joint_names.index(cmd.joint_name)
            current_q = robot.get_joint_positions()
            if current_q is not None:
                target_q = current_q.copy()
                target_q[joint_idx] = cmd.angle
                # Send dict-of-arms cmd via the underlying driver — only the
                # selected arm is commanded; the other one is left untouched.
                if hasattr(robot, '_client') and robot._client is not None:
                    robot._client.set_cmds({cmd.arm: target_q})
            return {"status": "success", "arm": cmd.arm}
        except Exception as e:
            return {"error": str(e)}
        
    # ====================================================================
    # soda_server-compatible endpoints (frontend talks to shell on :8080)
    # ====================================================================
    # The soda-ui frontend was originally written against the aiohttp
    # ``soda_server`` (recording / replay / gripper helpers). We host
    # equivalents here so the same UI can talk to shell directly.

    # ---- session/info ----

    @app.get("/system/info")
    async def system_info():
        cfg = app.state.config if hasattr(app.state, "config") else None
        return {
            "name": "SODA OS Shell",
            "version": "0.2.0",
            "mode": getattr(app.state, "current_mode", "realtime"),
            "teleop_running": (getattr(app.state, "teleop_process", None) is not None
                               and app.state.teleop_process.poll() is None),
            "arms": ["left", "right"],
            "config_mode": (cfg.get("mode") if cfg else None),
            # The shell is dual-arm only — this flag is just a hint the
            # soda-ui frontend reads to decide on its rendering path.
            "dual_mode": True,
        }

    # ---- gripper helpers (single-arm, defaults to left for soda-ui compat) ----

    @app.get("/api/joints/gripper")
    async def gripper_joints(arm: str = "left"):
        """Return gripper-related joint names for the selected arm."""
        dual = getattr(app.state, "dual", None)
        if dual is None or arm not in ("left", "right"):
            return {"joints": []}
        robot = getattr(dual, arm)
        # Joint names come from the (single-arm) URDF the per-arm service loaded.
        try:
            jn = []
            if robot.kinematics and hasattr(robot.kinematics, "joint_names"):
                jn = [n for n in robot.kinematics.joint_names if "gripper" in n]
        except Exception:
            jn = []
        if not jn:
            # Fall back to the known gripper joint name in firefly_y6 + GR100.
            jn = ["gripper_left_joint_1"]
        return {"arm": arm, "joints": jn}

    @app.get("/api/gripper/distance")
    async def gripper_distance(arm: str = "left"):
        """Read finger-tip distance for the selected arm's gripper."""
        dual = getattr(app.state, "dual", None)
        if dual is None or arm not in ("left", "right"):
            return JSONResponse(status_code=400, content={"error": "Invalid arm"})
        robot = getattr(dual, arm)
        q = robot.get_joint_positions()
        if q is None or len(q) <= 6:
            return JSONResponse(status_code=503, content={"error": "Gripper state unavailable"})
        # Same math as legacy WS: GR100 closes around 0.65 rad, 100→10 mm range.
        from .websockets.legacy import GRIP_MAX_DIST, GRIP_MIN_DIST, GRIP_CLOSE_ANGLE
        angle = float(q[6])
        ratio = max(0.0, min(1.0, angle / GRIP_CLOSE_ANGLE))
        dist = GRIP_MAX_DIST - ratio * (GRIP_MAX_DIST - GRIP_MIN_DIST)
        return {"arm": arm, "distance": dist, "angle": angle}

    class _GripperSetReq(BaseModel):
        distance: float
        arm: str = "left"

    @app.post("/api/gripper/set")
    async def gripper_set(req: _GripperSetReq):
        """Command a gripper distance (meters) on the selected arm."""
        dual = getattr(app.state, "dual", None)
        if dual is None or req.arm not in ("left", "right"):
            return JSONResponse(status_code=400, content={"error": "Invalid arm"})
        from .websockets.legacy import (
            GRIP_MAX_DIST, GRIP_MIN_DIST, GRIP_CLOSE_ANGLE,
        )
        dist = max(GRIP_MIN_DIST, min(GRIP_MAX_DIST, float(req.distance)))
        ratio = (GRIP_MAX_DIST - dist) / (GRIP_MAX_DIST - GRIP_MIN_DIST)
        angle = ratio * GRIP_CLOSE_ANGLE
        robot = getattr(dual, req.arm)
        q = robot.get_joint_positions()
        if q is None or len(q) <= 6:
            return JSONResponse(status_code=503, content={"error": "Gripper state unavailable"})
        target = q.copy()
        target[6] = angle
        if hasattr(robot, "_client") and robot._client is not None:
            robot._client.set_cmds({req.arm: target})
        return {"status": "ok", "arm": req.arm, "distance": dist, "angle": angle}

    # ---- recording / replay / mode ----

    import os
    import signal
    import socket
    import subprocess
    import sys
    from pathlib import Path
    from fastapi.responses import Response
    import msgpack

    from soda_os.recording import Hdf5ReplayManager

    # Teleop records raw HDF5 + MP4 episodes (incl. action labels) under
    #   recordings/hdf5/<ts>/   — replayed directly via Hdf5ReplayManager.
    # Override the root via SODA_RECORDINGS_DIR (e.g. a shared NFS).
    RECORDINGS_ROOT = os.environ.get(
        "SODA_RECORDINGS_DIR",
        os.path.join(os.getcwd(), "recordings"),
    )
    HDF5_DIR = os.path.join(RECORDINGS_ROOT, "hdf5")
    os.makedirs(HDF5_DIR, exist_ok=True)

    app.state.current_mode = "realtime"
    app.state.replay = None           # type: Optional[Hdf5ReplayManager]
    app.state.replay_task = None      # type: Optional[asyncio.Task]
    app.state.recording_dir = HDF5_DIR
    app.state.teleop_process = None   # type: Optional[subprocess.Popen]  (control)
    app.state.teleop_viewer = None    # type: Optional[subprocess.Popen]  (cv2 preview)
    # Set by the /ws/teleop handler; the legacy /ws broadcast sheds its heavy
    # per-frame work (camera JPEG + point cloud) while this is True so it
    # doesn't starve teleop command forwarding on the shared event loop.
    app.state.teleop_active = False
    app.state.teleop_clients = 0

    @app.get("/api/recordings")
    async def get_recordings():
        """List teleop HDF5 episodes under recordings/hdf5/ (have trajectory.h5).
        Produced by teleop (scripts/teleop_quest.py) and replayed directly via
        Hdf5ReplayManager."""
        if not os.path.isdir(HDF5_DIR):
            return {"files": []}
        files = []
        for name in sorted(os.listdir(HDF5_DIR)):
            d = os.path.join(HDF5_DIR, name)
            if os.path.isdir(d) and os.path.exists(os.path.join(d, "trajectory.h5")):
                files.append(name)
        return {"files": files}

    # ---- teleop launch (frontend "Teleop" button) ----
    # The backend owns the single ZMQ command client, so teleop runs as a
    # subprocess that connects back over /ws/teleop (no seq conflict). OpenCV
    # camera/record-prompt windows render on this host's display.
    repo_root = Path(__file__).resolve().parents[2]

    def _teleop_alive() -> bool:
        proc = getattr(app.state, "teleop_process", None)
        if proc is None:
            return False
        if proc.poll() is not None:        # exited — clear stale handle
            app.state.teleop_process = None
            return False
        return True

    class _TeleopStartReq(BaseModel):
        task: str = ""
        quest_ip: Optional[str] = None

    @app.post("/api/teleop/start")
    async def teleop_start(req: _TeleopStartReq = _TeleopStartReq()):
        if _teleop_alive():
            return JSONResponse(status_code=400, content={"error": "Teleop already running"})
        cfg = getattr(app.state, "config", None)
        backend_mode = (cfg.get("mode") if cfg else None) or "sim"
        port = int(os.environ.get("SODA_PORT", "8080"))
        # Pick a FREE key port per launch (default). A fixed port breaks if a
        # previous teleop didn't exit and still holds it: the new control can't
        # bind, the viewer connects to the stale process, and keys (record!) go
        # to the wrong arm. SODA_TELEOP_KEY_PORT can pin it if ever needed.
        key_port = int(os.environ.get("SODA_TELEOP_KEY_PORT", "0"))
        if key_port == 0:
            _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _s.bind(("127.0.0.1", 0))
            key_port = _s.getsockname()[1]
            _s.close()
        env = {**os.environ, "SODA_BACKEND": f"localhost:{port}"}
        # Control process — ZERO cv2, control loop on the MAIN thread (identical
        # hot path to the bare script). Keys arrive from the viewer via key_port.
        ctrl = [sys.executable, str(repo_root / "scripts" / "teleop_quest.py"),
                "--mode", str(backend_mode), "--windowed", "--key-port", str(key_port)]
        if req.task:
            ctrl += ["--task", req.task]
        if req.quest_ip:
            ctrl += ["--quest-ip", req.quest_ip]
        # Viewer process — owns the OpenCV camera window + "Record? y/n" prompt,
        # fully decoupled (own camera clients) so it can't steal control time.
        viewer = [sys.executable, str(repo_root / "scripts" / "teleop_viewer.py"),
                  "--mode", str(backend_mode), "--key-port", str(key_port)]
        try:
            cproc = subprocess.Popen(ctrl, cwd=str(repo_root), env=env, preexec_fn=os.setsid)
            vproc = subprocess.Popen(viewer, cwd=str(repo_root), env=env, preexec_fn=os.setsid)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Failed to launch teleop: {e}"})
        app.state.teleop_process = cproc
        app.state.teleop_viewer = vproc
        return {"status": "teleop_started", "pid": cproc.pid,
                "viewer_pid": vproc.pid, "mode": backend_mode}

    async def _kill_proc(proc, sig=signal.SIGINT, wait=10):
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except ProcessLookupError:
            return
        try:
            await asyncio.to_thread(proc.wait, wait)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    @app.post("/api/teleop/stop")
    async def teleop_stop():
        cproc = getattr(app.state, "teleop_process", None)
        vproc = getattr(app.state, "teleop_viewer", None)
        alive = ((cproc is not None and cproc.poll() is None) or
                 (vproc is not None and vproc.poll() is None))
        if not alive:
            app.state.teleop_process = None
            app.state.teleop_viewer = None
            return {"status": "not_running"}
        await _kill_proc(cproc)            # control first → saves in-progress episode
        await _kill_proc(vproc, wait=3)
        app.state.teleop_process = None
        app.state.teleop_viewer = None
        return {"status": "teleop_stopped"}

    @app.get("/api/teleop/status")
    async def teleop_status():
        proc = getattr(app.state, "teleop_process", None)
        running = _teleop_alive()
        return {"running": running, "pid": (proc.pid if running and proc else None)}

    @app.post("/api/shutdown")
    async def shutdown_recover():
        """Stop EVERYTHING and bring up zero-gravity for manual repositioning.

        Spawns scripts/recover_zerog.py DETACHED (own session) so it survives
        this backend being killed by it. That helper kills teleop/backend/
        servers, starts the zero-gravity launcher (arms become free to move),
        and shows an OpenCV popup; the operator hand-poses the arms to home and
        presses q/ESC there to shut the whole stack down. The frontend will go
        dark once the backend dies — the popup is the control surface after."""
        helper = [sys.executable, str(repo_root / "scripts" / "recover_zerog.py")]
        try:
            subprocess.Popen(
                helper, cwd=str(repo_root), env={**os.environ},
                start_new_session=True,                      # detach from backend
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Failed to start recovery: {e}"})
        return {"status": "recovering",
                "message": "Stopping everything and starting zero-gravity. "
                           "Use the popup window on the robot host to finish."}

    class _ModeReq(BaseModel):
        mode: str  # "realtime" | "replay"

    @app.post("/api/mode/set")
    async def set_mode(req: _ModeReq):
        if req.mode not in ("realtime", "replay"):
            return JSONResponse(status_code=400, content={"error": "Invalid mode"})
        app.state.current_mode = req.mode
        if req.mode == "realtime":
            _cancel_replay_task(app)
            app.state.replay = None
        return {"status": "success", "mode": req.mode}

    @app.get("/api/replay/status")
    async def replay_status():
        replay: Optional[Hdf5ReplayManager] = app.state.replay
        if replay is None:
            return {"is_loaded": False}
        return {
            "is_loaded": True,
            "total_frames": replay.total_frames,
            "current_frame": replay.current_frame_idx,
            "progress": replay.get_progress(),
            "duration": replay.get_duration(),
            "current_timestamp": replay.get_current_timestamp(),
            "is_playing": replay.is_playing,
        }

    class _ReplayLoadReq(BaseModel):
        filename: str   # a teleop episode dir under recordings/hdf5/ (or a .h5 path)

    @app.post("/api/replay/load")
    async def replay_load(req: _ReplayLoadReq):
        hdf5_dir = os.path.join(HDF5_DIR, req.filename)
        hdf5_h5 = (hdf5_dir if req.filename.endswith(".h5")
                   else os.path.join(hdf5_dir, "trajectory.h5"))
        if not os.path.isfile(hdf5_h5):
            return JSONResponse(status_code=404, content={
                "error": f"Recording {req.filename!r} not found under recordings/hdf5/"})

        _cancel_replay_task(app)
        try:
            app.state.replay = Hdf5ReplayManager(hdf5_h5)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Failed to load: {e}"})
        return {
            "status": "success",
            "format": "hdf5",
            "total_frames": app.state.replay.total_frames,
            "duration": app.state.replay.get_duration(),
        }

    @app.get("/api/replay/trajectory")
    async def replay_trajectory():
        replay: Optional[Hdf5ReplayManager] = app.state.replay
        if replay is None:
            return JSONResponse(status_code=400, content={"error": "No replay loaded"})
        return replay.get_trajectory()

    @app.get("/api/replay/chunk")
    async def replay_chunk(start_idx: int = 0, length: int = 300):
        replay: Optional[Hdf5ReplayManager] = app.state.replay
        if replay is None:
            return JSONResponse(status_code=400, content={"error": "No replay loaded"})
        chunk = replay.get_chunk(start_idx, length)
        packed = msgpack.packb(chunk, use_bin_type=True)
        return Response(content=packed, media_type="application/x-msgpack")

    # play drives the sim/real arm via the backend playback task; pause/seek/
    # step stop the task and move the playback head. The frontend follows by
    # polling /api/replay/status (and rendering the live WS state, since the
    # arm physically moves).
    class _ReplayControlReq(BaseModel):
        action: str                 # "play" | "pause" | "step_forward" | "step_backward" | "seek"
        frame: Optional[int] = None  # target frame for "seek"

    @app.post("/api/replay/control")
    async def replay_control(req: _ReplayControlReq):
        replay: Optional[Hdf5ReplayManager] = app.state.replay
        if replay is None:
            return JSONResponse(status_code=400, content={"error": "No replay loaded"})
        if req.action == "play":
            _cancel_replay_task(app)
            # SAFETY: replay physically moves the arms. Smoothly approach the
            # current frame's pose BEFORE streaming so there's no sudden jump.
            dual = getattr(app.state, "dual", None)
            left_q, right_q = replay.get_frame_joints(replay.current_frame_idx)
            if dual is not None and left_q is not None:
                print(f"[replay] ▶ play — approaching frame "
                      f"{replay.current_frame_idx} (arms will move)")

                def _approach():
                    import threading
                    tL = threading.Thread(target=dual.left.move_to_joints,
                                          args=(left_q[:6],), kwargs={"duration": 2.0, "blocking": True})
                    tR = threading.Thread(target=dual.right.move_to_joints,
                                          args=(right_q[:6],), kwargs={"duration": 2.0, "blocking": True})
                    tL.start(); tR.start(); tL.join(); tR.join()

                try:
                    await asyncio.to_thread(_approach)
                except Exception as e:
                    print(f"[replay] approach failed: {e}")
            replay.is_playing = True
            app.state.replay_task = asyncio.create_task(_run_replay_playback(app))
        elif req.action == "pause":
            replay.is_playing = False
            _cancel_replay_task(app)
        elif req.action == "step_forward":
            replay.is_playing = False
            _cancel_replay_task(app)
            replay.seek_to_frame(replay.current_frame_idx + 1)
        elif req.action == "step_backward":
            replay.is_playing = False
            _cancel_replay_task(app)
            replay.seek_to_frame(replay.current_frame_idx - 1)
        elif req.action == "seek":
            replay.is_playing = False
            _cancel_replay_task(app)
            if req.frame is not None:
                replay.seek_to_frame(int(req.frame))
        else:
            return JSONResponse(status_code=400, content={"error": "Invalid action"})
        return {"status": "ok", "is_playing": replay.is_playing,
                "current_frame": replay.current_frame_idx}

    # ==================== MJPEG Video Stream ====================

    @app.get("/camera/stream")
    async def camera_mjpeg_stream(cam: str = "left"):
        """
        MJPEG video stream for low-latency camera viewing.

        Args:
            cam: which wrist camera to stream — "left" or "right" (default left)

        Usage in HTML: <img src="http://localhost:8000/camera/stream?cam=right">
        """
        import cv2

        cameras = getattr(app.state, "cameras", {}) or {}
        if cam not in cameras:
            return JSONResponse(
                status_code=400,
                content={"error": f"unknown cam {cam!r}; available: {list(cameras.keys())}"},
            )
        camera = cameras[cam]

        async def generate_frames():
            rate = 15  # Hz
            while True:
                try:
                    rgb = camera.get_rgb() if camera else None
                    if rgb is not None:
                        # Convert to JPEG
                        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                        _, buffer = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])

                        # MJPEG frame
                        yield (
                            b'--frame\r\n'
                            b'Content-Type: image/jpeg\r\n\r\n' +
                            buffer.tobytes() +
                            b'\r\n'
                        )

                    await asyncio.sleep(1.0 / rate)

                except Exception as e:
                    print(f"[MJPEG] Error: {e}")
                    await asyncio.sleep(1.0)

        return StreamingResponse(
            generate_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame"
        )

    # ==================== Health Check ====================

    @app.get("/health")
    async def health_check():
        """Dual-arm health check — reports per-arm robot + camera status."""
        dual = getattr(app.state, 'dual', None)
        cameras = getattr(app.state, 'cameras', {}) or {}

        robot_status = {}
        if dual is not None:
            robot_status = {
                "left":  dual.left.is_connected,
                "right": dual.right.is_connected,
            }
        camera_status = {arm: cam.is_connected for arm, cam in cameras.items()}

        all_ok = (
            bool(robot_status) and all(robot_status.values())
            and bool(camera_status) and all(camera_status.values())
        )
        return {
            "status": "ok" if all_ok else "degraded",
            "robots": robot_status,
            "cameras": camera_status,
            "timestamp": time.time(),
        }

    @app.get("/")
    async def root():
        """Shell root endpoint."""
        return {
            "name": "SODA OS Shell",
            "version": "0.2.0",
            "docs": "/docs",
            "endpoints": {
                "rest": {
                    "robot": "/robot",
                    "camera": "/camera",
                    "health": "/health",
                },
                "websocket": {
                    "state": "/ws/state",
                    "control": "/ws/control",
                    "legacy": "/ws",
                },
                "stream": {
                    "camera": "/camera/stream",
                },
                "legacy": {
                    "urdf": "/urdf",
                    "joint_set": "/api/joint/set",
                    "assets": "/assets/*",
                },
            }
        }

    # ==================== Static Files (URDF assets) ====================
    # Mount static files for URDF meshes.
    # Use repo-relative paths to work on macOS/Linux/CI.
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]  # .../soda

    # Possible URDF asset locations (first match wins)
    asset_paths = [
        # soda-ui legacy server public directory (contains firefly_y6_gr100/...)
        repo_root / "soda-ui" / "soda_server" / "public",
        # hex_zmq_servers URDF directory (contains firefly_y6/, meshes/, ...)
        repo_root / "hex_zmq_servers" / "hex_zmq_servers" / "robot" / "hexarm" / "urdf",
    ]

    for asset_path in asset_paths:
        if asset_path.exists():
            app.mount("/assets", StaticFiles(directory=str(asset_path)), name="assets")
            print(f"[Shell] Static assets mounted from: {asset_path}")
            break
    else:
        print("[Shell] Warning: No URDF assets directory found")

    return app


# Default app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    # NOTE: bind to 8000 to avoid colliding with soda-ui/soda_server (port 8080).
    uvicorn.run(app, host="0.0.0.0", port=8000)
