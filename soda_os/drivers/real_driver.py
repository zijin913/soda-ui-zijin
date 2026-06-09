#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Real-hardware drivers for the Firefly Y6 dual-arm rig.

``RealRobotDriver`` wraps two ``HexRobotHexarmClient`` instances (one per
arm) and ``RealCameraDriver`` wraps the two wrist RealSense clients (and
optionally the side camera). Both expose the same dict-of-arms schema as
:class:`SimDriver`, so application code can swap sim/real with one config
flag.

Expected server topology (matches ``launchers/launch_servers.py --mode real``):

    left_arm_srv   127.0.0.1:12345
    right_arm_srv  127.0.0.1:12350
    left_cam_srv   127.0.0.1:12346
    right_cam_srv  127.0.0.1:12351
    side_cam_srv   127.0.0.1:12347   (optional)
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import numpy as np

from .base import CameraDriverBase, RobotDriverBase


# --------- defaults matching the topology in `launch_servers.py --mode real` ---------

_DEFAULT_ROBOT = {
    "left":  {"ip": "127.0.0.1", "port": 12345},
    "right": {"ip": "127.0.0.1", "port": 12350},
    "realtime_mode": True,
    "client_timeout_ms": 200,
    "state_warmup_s": 0.3,
}

_DEFAULT_CAMERA = {
    "left":  {"ip": "127.0.0.1", "port": 12346},
    "right": {"ip": "127.0.0.1", "port": 12351},
    "side":  {"ip": "127.0.0.1", "port": 12347},
    "realtime_mode": False,   # cams misbehave under realtime at low fps
    "client_timeout_ms": 1000,
    "include_side": True,
}


class RealRobotDriver(RobotDriverBase):
    """Two ``HexRobotHexarmClient`` instances under one dual-arm interface."""

    ARMS = ("left", "right")

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = dict(_DEFAULT_ROBOT)
        if config:
            cfg.update(config)
        self.config = cfg
        self._clients: Dict[str, Any] = {}
        self._connected = False

    def connect(self) -> bool:
        if self._clients:
            return self._connected

        try:
            from hex_zmq_servers.robot.hexarm import HexRobotHexarmClient
        except Exception as e:
            print(f"RealRobotDriver import failed: {e}")
            return False

        ok = True
        for arm in self.ARMS:
            arm_cfg = self.config[arm]
            net = {
                "ip": arm_cfg["ip"],
                "port": arm_cfg["port"],
                "realtime_mode": self.config.get("realtime_mode", True),
                "client_timeout_ms": self.config.get("client_timeout_ms", 200),
            }
            try:
                cli = HexRobotHexarmClient(net)
                if cli.get_dofs() is None:
                    print(f"[{arm}] get_dofs returned None — server up?")
                    ok = False
                self._clients[arm] = cli
            except Exception as e:
                print(f"RealRobotDriver connect({arm}) failed: {e}")
                ok = False

        if ok:
            time.sleep(self.config.get("state_warmup_s", 0.3))
            self._connected = True
        return self._connected

    def disconnect(self) -> None:
        for cli in self._clients.values():
            try:
                cli.close()
            except Exception:
                pass
        self._clients.clear()
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ---- robot interface ----

    def get_dofs(self) -> Optional[int]:
        if not self._connected:
            return None
        try:
            dofs = self._clients["left"].get_dofs()
            return int(dofs[0]) if dofs is not None else None
        except Exception:
            return None

    def get_limits(self) -> Optional[np.ndarray]:
        if not self._connected:
            return None
        try:
            # Both arms are identical hardware; one set of limits suffices.
            return self._clients["left"].get_limits()
        except Exception:
            return None

    def get_states(self, arm: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # realtime_mode returns (None, None) when no fresh frame has arrived
        # since the previous read. With dual arms polled back-to-back this
        # happens often, so each arm gets up to 3 tries with a tiny sleep.
        # Pass ``arm`` to read a single client — avoids two parallel callers
        # (e.g. left/right go_home threads) stealing each other's frame.
        if not self._connected:
            return None
        arms = (arm,) if arm is not None else self.ARMS
        out: Dict[str, Any] = {}
        for a in arms:
            arm_state = None
            for attempt in range(3):
                try:
                    hdr, st = self._clients[a].get_states()
                except Exception as e:
                    if attempt == 2:
                        print(f"get_states({a}) error: {e}")
                    time.sleep(0.005)
                    continue
                if st is not None:
                    ts = hdr.get("ts", {})
                    arm_state = {
                        "position": st[:, 0].copy(),
                        "velocity": st[:, 1].copy(),
                        "torque":   st[:, 2].copy(),
                        "timestamp": ts.get("s", 0) + ts.get("ns", 0) * 1e-9,
                    }
                    break
                time.sleep(0.005)
            if arm_state is None:
                return None
            out[a] = arm_state
        return out

    def reset_cmd_seq(self) -> None:
        """Re-baseline command seq on each per-arm client (see base)."""
        for cli in self._clients.values():
            try:
                if hasattr(cli, "seq_clear"):
                    cli.seq_clear()          # server-side counter → -1
                if hasattr(cli, "_cmds_seq"):
                    cli._cmds_seq = 0        # our next send is accepted (small delta)
            except Exception as e:
                print(f"reset_cmd_seq error: {e}")

    def set_cmds(self, cmds: Dict[str, np.ndarray]) -> bool:
        """Send commands to both arms in parallel.

        Each per-arm ZMQ client owns its own socket, so two threads can
        each send REQ + wait REP simultaneously without contention. At
        ~12-15 ms per arm, parallel cuts a 30 Hz teleop tick by ~12 ms.
        """
        if not self._connected:
            return False
        pending = [(arm, cmds.get(arm)) for arm in self.ARMS if cmds.get(arm) is not None]
        if not pending:
            return True
        if len(pending) == 1:
            # Single-arm command — no point spinning threads.
            arm, cmd = pending[0]
            try:
                self._clients[arm].set_cmds(np.asarray(cmd))
                return True
            except Exception as e:
                print(f"set_cmds({arm}) error: {e}")
                return False

        # Lazy-init a tiny long-lived pool — fresh ThreadPoolExecutor per
        # tick would defeat the parallelism gain.
        if not hasattr(self, "_cmd_pool") or self._cmd_pool is None:
            from concurrent.futures import ThreadPoolExecutor
            self._cmd_pool = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="real_robot_setcmds",
            )

        def _send(arm_cmd):
            arm, cmd = arm_cmd
            try:
                self._clients[arm].set_cmds(np.asarray(cmd))
                return True
            except Exception as e:
                print(f"set_cmds({arm}) error: {e}")
                return False

        futures = [self._cmd_pool.submit(_send, p) for p in pending]
        return all(f.result() for f in futures)


class RealCameraDriver(CameraDriverBase):
    """Left+right wrist RealSense (and optionally side) under one interface."""

    WRIST_ARMS = ("left", "right")

    # Consecutive misses (None reply OR exception) before we treat a
    # camera client's ZMQ REQ socket as deadlocked and rebuild it.
    # ~10 misses at 30 Hz ≈ 0.33 s of nothing — well above the normal
    # transient drop window, below a noticeable user-visible stall.
    _MAX_CONSECUTIVE_FAILS = 10

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = dict(_DEFAULT_CAMERA)
        if config:
            cfg.update(config)
        self.config = cfg
        self._clients: Dict[str, Any] = {}     # "left", "right", optional "side"
        self._intrinsics: Optional[Dict[str, np.ndarray]] = None
        self._connected = False
        # Per-camera health counter — consecutive get_rgb/get_depth misses.
        self._fail_counts: Dict[str, int] = {}

    def connect(self) -> bool:
        if self._clients:
            return self._connected

        try:
            from hex_zmq_servers.cam.realsense import HexCamRealsenseClient
        except Exception as e:
            print(f"RealCameraDriver import failed: {e}")
            return False

        cam_keys = list(self.WRIST_ARMS)
        if self.config.get("include_side", True):
            cam_keys.append("side")

        # Number of intri probes per camera and the back-off between
        # them. Cameras need a beat after launch_servers.py to warm
        # their RealSense pipeline; a single failure here used to
        # abort the whole driver permanently, leaving the shell
        # ``_connected=False`` and never able to recover.
        intri_attempts = 8
        intri_backoff_s = 0.3

        intrinsics: Dict[str, np.ndarray] = {}
        for key in cam_keys:
            cam_cfg = self.config[key]
            net = {
                "ip": cam_cfg["ip"],
                "port": cam_cfg["port"],
                "realtime_mode": self.config.get("realtime_mode", False),
                "client_timeout_ms": self.config.get("client_timeout_ms", 1000),
            }
            cli = None
            try:
                cli = HexCamRealsenseClient(net)
            except Exception as e:
                print(f"[{key}_cam] client ctor failed: {e}")
                continue   # keep trying the other cameras

            intri = None
            for attempt in range(intri_attempts):
                try:
                    _, intri = cli.get_intri()
                except Exception as e:
                    if attempt == intri_attempts - 1:
                        print(f"[{key}_cam] get_intri raised after "
                              f"{intri_attempts} tries: {e}")
                    intri = None
                if intri is not None:
                    break
                time.sleep(intri_backoff_s)

            if intri is not None:
                intrinsics[key] = np.array([
                    [intri[0], 0.0,      intri[2]],
                    [0.0,      intri[1], intri[3]],
                    [0.0,      0.0,      1.0],
                ])
                print(f"[{key}_cam] connected")
            else:
                # Keep the client anyway — the self-healing path in
                # _collect will rebuild it once frames start being
                # requested. Setting _intrinsics for this key is
                # deferred until _rebuild_client picks it up.
                print(f"[{key}_cam] no intrinsics after warm-up; "
                      "will retry on first frame request")
            self._clients[key] = cli
            self._fail_counts[key] = 0

        if not self._clients:
            print("RealCameraDriver: no cameras connected")
            return False

        self._intrinsics = intrinsics or {}
        # Mark connected so _collect runs and self-healing can kick
        # in. Even cams that lacked intrinsics during warm-up will
        # be rebuilt on first frame attempt.
        self._connected = True
        return True

    def _rebuild_client(self, key: str) -> None:
        """Tear down + rebuild one camera client.

        ZMQ REQ sockets deadlock the first time they miss a reply (any
        timeout / dropped frame), and there's no recovery short of
        recreating the socket. This is hit-or-miss in long-running
        shells; ``_collect`` calls this when a client returns None
        ``_MAX_CONSECUTIVE_FAILS`` times in a row.
        """
        try:
            from hex_zmq_servers.cam.realsense import HexCamRealsenseClient
        except Exception as e:
            print(f"[{key}_cam] rebuild import failed: {e}")
            return

        old = self._clients.get(key)
        try:
            if old is not None:
                old.close()
        except Exception:
            pass

        cam_cfg = self.config[key]
        net = {
            "ip": cam_cfg["ip"],
            "port": cam_cfg["port"],
            "realtime_mode": self.config.get("realtime_mode", False),
            "client_timeout_ms": self.config.get("client_timeout_ms", 1000),
        }
        try:
            new_cli = HexCamRealsenseClient(net)
            self._clients[key] = new_cli
            self._fail_counts[key] = 0
            # Refresh intrinsics; the server occasionally renegotiates
            # resolution on its end (e.g. after a USB re-enumeration).
            try:
                _, intri = new_cli.get_intri()
                if intri is not None and self._intrinsics is not None:
                    self._intrinsics[key] = np.array([
                        [intri[0], 0.0,      intri[2]],
                        [0.0,      intri[1], intri[3]],
                        [0.0,      0.0,      1.0],
                    ])
            except Exception:
                pass
            msg = (f"[{key}_cam] ZMQ client rebuilt after "
                   f"{self._MAX_CONSECUTIVE_FAILS} consecutive misses")
            print(msg)
            try:
                with open("/tmp/soda_cam_diag.log", "a") as f:
                    f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
            except Exception:
                pass
        except Exception as e:
            print(f"[{key}_cam] rebuild failed: {e}")
            # Mark as unusable; the next _collect will skip this key.
            self._clients[key] = None

    def disconnect(self) -> None:
        for cli in self._clients.values():
            try:
                cli.close()
            except Exception:
                pass
        self._clients.clear()
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ---- camera interface ----

    def get_rgb(self) -> Optional[Dict[str, np.ndarray]]:
        return self._collect(depth=False)

    def get_depth(self) -> Optional[Dict[str, np.ndarray]]:
        return self._collect(depth=True)

    def get_intrinsics(self) -> Optional[Dict[str, np.ndarray]]:
        return self._intrinsics

    def get_side(self, depth: bool = False) -> Optional[np.ndarray]:
        """Convenience: pull a frame from the optional side camera."""
        if not self._connected or "side" not in self._clients:
            return None
        try:
            fn = self._clients["side"].get_depth if depth else self._clients["side"].get_rgb
            _, img = fn()
            if img is not None and depth and img.dtype == np.uint16:
                img = img.astype(np.float32) / 1000.0
            return img
        except Exception:
            return None

    def _try_capture(self, cli, depth: bool):
        """One read attempt, normalised to ``(img_or_None, exc_str_or_None)``."""
        try:
            fn = cli.get_depth if depth else cli.get_rgb
            _, img = fn()
            if img is not None and depth and img.dtype == np.uint16:
                img = img.astype(np.float32) / 1000.0
            return img, None
        except Exception as e:
            return None, repr(e)

    def _collect(self, depth: bool) -> Optional[Dict[str, np.ndarray]]:
        """Iterate every connected client (wrist arms + optional side).

        Per-camera self-healing: ``_MAX_CONSECUTIVE_FAILS`` strikes in a
        row triggers a ZMQ client rebuild for that camera, and the NEW
        client is retried in the same call so the WS frame isn't lost.
        """
        if not self._connected:
            return None
        out: Dict[str, np.ndarray] = {}
        for key in list(self._clients):
            cli = self._clients.get(key)
            if cli is None:
                continue
            img = None
            last_err = None
            for _ in range(3):
                img, err = self._try_capture(cli, depth)
                if img is not None:
                    break
                if err is not None:
                    last_err = err
                time.sleep(0.05)
            if img is None:
                self._fail_counts[key] = self._fail_counts.get(key, 0) + 1
                self._log_miss(key, depth, last_err)
                if self._fail_counts[key] >= self._MAX_CONSECUTIVE_FAILS:
                    self._rebuild_client(key)
                    new_cli = self._clients.get(key)
                    if new_cli is not None:
                        # Give the freshly-built socket one more shot in
                        # this same call so we don't drop the WS frame.
                        img, _err = self._try_capture(new_cli, depth)
            if img is not None:
                out[key] = img
                self._fail_counts[key] = 0
        return out or None

    def _log_miss(self, key: str, depth: bool, err: Optional[str]) -> None:
        """Append a diagnostic line to /tmp/soda_cam_diag.log (rate-limited).

        Used to debug long-running shells where camera frames silently
        stop arriving — pts/14 print() output is invisible to harnesses
        watching the shell from outside, but this file is always tail'able.
        """
        cnt = self._fail_counts.get(key, 0)
        # Only log on transitions (first miss after a success) and on
        # every threshold tick to keep the file size sane.
        if cnt == 1 or cnt % self._MAX_CONSECUTIVE_FAILS == 0:
            try:
                with open("/tmp/soda_cam_diag.log", "a") as f:
                    f.write(
                        f"{time.strftime('%H:%M:%S')} {key} "
                        f"{'depth' if depth else 'rgb'} miss #{cnt}"
                        f"{' err=' + err if err else ''}\n"
                    )
            except Exception:
                pass
