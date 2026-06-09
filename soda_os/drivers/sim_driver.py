#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Dual-arm Firefly Y6 MuJoCo simulation driver.

Wraps `HexMujocoFireflyY6DualClient` from hex_zmq_servers. One ZMQ port
serves both arms + scene objects + sim cameras.

States/cmds use dict-of-arms schema:
    states = {
        "left":  {"position": ndarray(7,), "velocity": ndarray(7,), "torque": ndarray(7,), "timestamp": float},
        "right": {"position": ndarray(7,), "velocity": ndarray(7,), "torque": ndarray(7,), "timestamp": float},
        "obj":   ndarray(...),   # optional, scene object pose
    }
    cmds = {
        "left":  ndarray(7,),    # 6 joints + 1 gripper (GR100 in [0, 0.9] rad)
        "right": ndarray(7,),
    }
"""

import time
from typing import Any, Dict, Optional

import numpy as np

from .base import CameraDriverBase, RobotDriverBase


class SimDriver(RobotDriverBase, CameraDriverBase):
    """MuJoCo dual-arm simulation driver (firefly_y6 + GR100)."""

    ARMS = ("left", "right")

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config:
                - ip:    Server IP (default "127.0.0.1")
                - port:  ZMQ port  (default 12345)
        """
        self.config = config or {}
        self._client = None
        self._connected = False
        # Camera caches (filled on connect / first access)
        self._intrinsics: Optional[Dict[str, np.ndarray]] = None
        self._cam2gripper: Optional[Dict[str, np.ndarray]] = None
        # Per-arm last-known RGB / depth frame. The underlying sim client
        # runs in realtime_mode, so each successful get_X(arm) consumes
        # the seq and the next call within the same tick returns None.
        # When two CameraServices share this driver (one for each wrist),
        # the second one would otherwise always see None — we cache the
        # most recent valid frame per arm so both consumers can read it.
        self._last_rgb: Dict[str, np.ndarray] = {}
        self._last_depth: Dict[str, np.ndarray] = {}

    def connect(self) -> bool:
        if self._client is not None:
            return self._connected

        net_config = {
            "ip": self.config.get("ip", "127.0.0.1"),
            "port": self.config.get("port", 12345),
            "realtime_mode": True,
            "deque_maxlen": 10,
            "client_timeout_ms": 200,
            "server_timeout_ms": 1000,
            "server_num_workers": 4,
        }

        try:
            from hex_zmq_servers.mujoco.firefly_y6.mujoco_firefly_y6_dual_cli import (
                HexMujocoFireflyY6DualClient,
            )

            self._client = HexMujocoFireflyY6DualClient(net_config)
            self._connected = self._client.get_dofs() is not None
            if self._connected:
                self._fetch_intrinsics()
            return self._connected
        except Exception as e:
            print(f"SimDriver connect failed: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ============== Robot Interface ==============

    def get_dofs(self) -> Optional[int]:
        """DOFs per arm (both arms are identical firefly_y6)."""
        if not self._connected:
            return None
        try:
            dofs = self._client.get_dofs()
            return int(dofs[0]) if dofs is not None else None
        except Exception:
            return None

    def get_limits(self) -> Optional[np.ndarray]:
        """Joint limits per arm (both arms share the same limits)."""
        if not self._connected:
            return None
        try:
            return self._client.get_limits()
        except Exception:
            return None

    def get_states(self, arm: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Snapshot arm state (+ scene objects when reading all arms).

        MuJoCo can need a few retries before first frames arrive. Pass ``arm``
        to read a single arm — avoids two parallel callers stealing each
        other's realtime frame.
        """
        if not self._connected:
            return None

        arms = (arm,) if arm is not None else self.ARMS
        out: Dict[str, Any] = {}
        for a in arms:
            for attempt in range(3):
                try:
                    hdr, st = self._client.get_states(robot_name=a)
                    if st is not None:
                        ts = hdr.get("ts", {})
                        out[a] = {
                            "position": st[:, 0].copy(),
                            "velocity": st[:, 1].copy(),
                            "torque":   st[:, 2].copy(),
                            "timestamp": ts.get("s", 0) + ts.get("ns", 0) * 1e-9,
                        }
                        break
                    time.sleep(0.01)
                except Exception as e:
                    if attempt == 2:
                        print(f"get_states({a}) error: {e}")
                    else:
                        time.sleep(0.01)
            if a not in out:
                return None

        # Scene objects only matter for the full snapshot; skip on per-arm reads.
        if arm is None:
            try:
                hdr, pose = self._client.get_states(robot_name="obj")
                if pose is not None:
                    out["obj"] = pose
            except Exception:
                pass
        return out

    def reset_cmd_seq(self) -> None:
        """Re-baseline command seq on the shared sim client (see base).
        The sim dual client tracks ``_cmds_seq`` as a per-arm dict."""
        try:
            if hasattr(self._client, "seq_clear"):
                self._client.seq_clear()
            cs = getattr(self._client, "_cmds_seq", None)
            if isinstance(cs, dict):
                for k in cs:
                    cs[k] = 0
            elif cs is not None:
                self._client._cmds_seq = 0
        except Exception as e:
            print(f"reset_cmd_seq error: {e}")

    def set_cmds(self, cmds: Dict[str, np.ndarray]) -> bool:
        """Send joint+gripper commands to both arms.

        Args:
            cmds: ``{"left": ndarray, "right": ndarray}`` — each (n_dofs,).
                  Missing arms are not commanded this tick.
        """
        if not self._connected:
            return False
        ok = True
        for arm in self.ARMS:
            cmd = cmds.get(arm)
            if cmd is None:
                continue
            try:
                self._client.set_cmds(np.asarray(cmd), robot_name=arm)
            except Exception as e:
                print(f"set_cmds({arm}) error: {e}")
                ok = False
        return ok

    def reset(self) -> bool:
        if not self._connected:
            return False
        try:
            return self._client.reset()
        except Exception:
            return False

    # ============== Camera Interface ==============

    def get_rgb(self) -> Optional[Dict[str, np.ndarray]]:
        """RGB frames from both wrist cameras (placeholder cameras in sim).

        Returns ``{"left": ndarray, "right": ndarray}`` or None on failure.
        Missing-arm keys are dropped.
        """
        return self._collect_frames(depth=False)

    def get_depth(self) -> Optional[Dict[str, np.ndarray]]:
        """Depth frames from both wrist cameras (meters).

        Returns ``{"left": ndarray, "right": ndarray}`` or None on failure.
        """
        return self._collect_frames(depth=True)

    def _collect_frames(self, depth: bool) -> Optional[Dict[str, np.ndarray]]:
        """Per-arm fetch (left/right wrist + optional side), with per-arm
        caching across calls.

        Each call walks both arms (and the side cam if the sim exposes one)
        and tries to grab a fresh frame from the sim client. When
        realtime_mode is on the client returns ``None`` if the latest queued
        frame has the same sequence as last read. We fall back to the most
        recent valid frame per arm so that downstream CameraService
        instances sharing this driver always see images — without the
        cache, the second caller within a tight loop got None.
        """
        if not self._connected:
            return None
        cache = self._last_depth if depth else self._last_rgb
        out: Dict[str, np.ndarray] = {}
        # Wrist cameras: get_depth(camera_name=arm) / get_rgb(camera_name=arm)
        for arm in self.ARMS:
            try:
                fn = self._client.get_depth if depth else self._client.get_rgb
                _, img = fn(camera_name=arm)
            except Exception:
                img = None
            if img is not None:
                if depth and img.dtype == np.uint16:
                    img = img.astype(np.float32) / 1000.0
                cache[arm] = img
                out[arm] = img
            elif arm in cache:
                out[arm] = cache[arm]

        # Side camera (third-person view) lives on a separate method pair on
        # the dual cli. Treat it as another camera under the "side" key so
        # CameraService(cam_name="side") works uniformly.
        side_fn = getattr(
            self._client,
            "get_side_depth" if depth else "get_side_rgb",
            None,
        )
        if side_fn is not None:
            try:
                _, img = side_fn()
            except Exception:
                img = None
            if img is not None:
                if depth and img.dtype == np.uint16:
                    img = img.astype(np.float32) / 1000.0
                cache["side"] = img
                out["side"] = img
            elif "side" in cache:
                out["side"] = cache["side"]
        return out or None

    def get_intrinsics(self) -> Optional[Dict[str, np.ndarray]]:
        """Per-arm 3x3 intrinsic matrices.

        Returns ``{"left": K_left, "right": K_right}``. Sim cameras are
        identical pinhole MuJoCo cameras, but each row of the server's
        ``_intri`` array is independent so we honor that.
        """
        if not self._connected:
            return None
        if self._intrinsics is None:
            self._fetch_intrinsics()
        return self._intrinsics

    def get_cam2gripper(self) -> Optional[Dict[str, np.ndarray]]:
        """Per-arm ``T_cam2link6`` (4x4, OpenCV camera frame -> link_6 frame).

        Derived from the live ``robot_left.xml`` / ``robot_right.xml`` MJCF
        chain (must stay in sync with what's actually in those files):

            link_6 -> gripper_base_link : identity (pos=[0,0,0], quat=[1,0,0,0])
                                          GR100 lobster claw mounts along
                                          link_6's +Z, no extra rotation.
            gripper_base_link -> *_end_camera (MuJoCo/OpenGL frame):
                                          pos=[-0.105, 0, 0.066],
                                          quat=[0.1830127, 0.6830127,
                                                -0.6830127, -0.1830127]
                                          (transformed from archer's
                                          (0.066, 0, 0.105) by archer's
                                          gripper_base rotation, so the
                                          camera ends up at the same
                                          physical place on the gripper
                                          as archer_l6y's wrist cam)
            * + OpenGL -> OpenCV swap (Y, Z flip).

        Returns ``{"left": T, "right": T}``. Both arms are kinematically
        identical so the two matrices are equal.
        """
        if not self._connected:
            return None
        if self._cam2gripper is None:
            T = self._compute_sim_cam2link6()
            self._cam2gripper = {"left": T, "right": T.copy()}
        return self._cam2gripper

    # ============== Camera transform helpers ==============

    def _fetch_intrinsics(self) -> None:
        """Pull camera intrinsics from the sim server once.

        Server returns a (2, 4) array for the wrist cams (row 0 = left,
        row 1 = right, each as ``[fx, fy, cx, cy]``). Side cam intrinsics
        come from a separate ``get_side_intri`` call when available.
        """
        out: Dict[str, np.ndarray] = {}

        def _K(row) -> np.ndarray:
            fx, fy, cx, cy = (float(v) for v in row)
            return np.array([[fx, 0.0, cx],
                             [0.0, fy, cy],
                             [0.0, 0.0, 1.0]])

        try:
            _, intri = self._client.get_intri()
        except Exception as e:
            print(f"get_intri failed: {e}")
            intri = None
        if intri is not None:
            intri = np.asarray(intri)
            if intri.ndim == 2 and intri.shape == (2, 4):
                out["left"]  = _K(intri[0])
                out["right"] = _K(intri[1])
            else:
                print(f"unexpected intri shape: {intri.shape}")

        # Side cam intrinsics (optional — only if the cli exposes the call).
        get_side_intri = getattr(self._client, "get_side_intri", None)
        if get_side_intri is not None:
            try:
                _, side_intri = get_side_intri()
            except Exception:
                side_intri = None
            if side_intri is not None:
                side_intri = np.asarray(side_intri)
                if side_intri.ndim == 1 and side_intri.shape == (4,):
                    out["side"] = _K(side_intri)
                elif side_intri.ndim == 2 and side_intri.shape == (1, 4):
                    out["side"] = _K(side_intri[0])
        self._intrinsics = out or None

    @staticmethod
    def _compute_sim_cam2link6() -> np.ndarray:
        """Chain link_6 -> gripper_base_link -> end_camera -> OpenCV.

        MuJoCo body pos/quat give the child frame expressed in the parent
        frame, so the resulting homogeneous T maps a point FROM the child
        frame TO the parent frame (p_parent = T @ p_child).
        """

        def quat_to_mat(q):
            w, x, y, z = q
            return np.array([
                [1 - 2 * (y * y + z * z),     2 * (x * y - w * z),     2 * (x * z + w * y)],
                [    2 * (x * y + w * z), 1 - 2 * (x * x + z * z),     2 * (y * z - w * x)],
                [    2 * (x * z - w * y),     2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
            ])

        def make_T(R, t):
            T = np.eye(4)
            T[:3, :3] = R
            T[:3, 3] = t
            return T

        # link_6 -> gripper_base_link: identity in firefly_y6 (no extra rotation)
        T_link6_gbl = np.eye(4)

        # gripper_base_link -> end_camera (MuJoCo / OpenGL frame).
        # These values MUST match what's currently in robot_left.xml /
        # robot_right.xml. They're the result of rotating archer_l6y's
        # original (pos=(0.066,0,0.105), quat=(0.6123724,...)) by archer's
        # gripper_base quat (0.7071068, 0, -0.7071068, 0) so the wrist
        # camera lands at the same physical place on firefly_y6.
        T_gbl_cam_mj = make_T(
            quat_to_mat([0.1830127, 0.6830127, -0.6830127, -0.1830127]),
            [-0.105, 0.0, 0.066],
        )

        # OpenCV camera frame -> MuJoCo camera frame (Y, Z flip)
        T_mj_cv = make_T(np.diag([1.0, -1.0, -1.0]), [0.0, 0.0, 0.0])

        return T_link6_gbl @ T_gbl_cam_mj @ T_mj_cv

    # ============== Simulation-specific ==============

    def get_obj_pose(self) -> Optional[np.ndarray]:
        """Raw scene-object pose from the sim."""
        if not self._connected:
            return None
        try:
            _, pose = self._client.get_states(robot_name="obj")
            return pose
        except Exception:
            return None
