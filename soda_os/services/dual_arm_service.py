#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
DualArmRobotService — thin orchestration over two per-arm RobotService instances.

Each arm is a normal :class:`RobotService` with its own kinematics,
dynamics, calibration and motion primitives. They share a single
dict-of-arms robot driver so the underlying ZMQ clients are not
duplicated.

Typical usage::

    from soda_os.drivers import DriverFactory
    from soda_os.services import RobotService
    from soda_os.services.dual_arm_service import DualArmRobotService

    factory = DriverFactory(mode="real", config={})
    shared_driver = factory.create_robot_driver()

    left  = RobotService(config=cfg, robot_client=shared_driver, arm_name="left")
    right = RobotService(config=cfg, robot_client=shared_driver, arm_name="right")

    dual = DualArmRobotService(left=left, right=right)
    dual.connect()
    state = dual.get_states()
    print(state["left"].ee_position, state["right"].ee_position)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional, Tuple

from .robot_service import RobotService, RobotState


class DualArmRobotService:
    """Group two per-arm :class:`RobotService` instances under one handle.

    All per-arm logic (IK, FK, planning, gripper) lives in the individual
    services; this class only adds connect/disconnect coordination and a
    few dict-returning convenience methods.
    """

    def __init__(self, left: RobotService, right: RobotService):
        if left._arm_name == right._arm_name:
            raise ValueError(
                "left and right RobotService must target different arms "
                f"(got both '{left._arm_name}')"
            )
        self.left = left
        self.right = right
        # Long-lived 2-worker pool reused by every parallel dual-arm call
        # (get_states_parallel + go_home + stop). Without persistence each
        # 30 Hz teleop tick would spawn 2 threads → defeats the purpose.
        self._pool = ThreadPoolExecutor(max_workers=2,
                                        thread_name_prefix="dual_arm")

    # ---------------- lifecycle ----------------

    def connect(self) -> bool:
        """Connect both arms.

        Returns True iff both arms connect successfully. Idempotent when
        the two services share a driver (the underlying driver's connect
        is a no-op the second time).
        """
        ok_left = self.left.connect()
        ok_right = self.right.connect()
        return ok_left and ok_right

    def disconnect(self) -> None:
        # Disconnecting the shared driver via either service is enough;
        # the second call is a no-op on a driver that's already torn down.
        self.left.disconnect()
        self.right.disconnect()

    @property
    def is_connected(self) -> bool:
        return self.left.is_connected and self.right.is_connected

    # ---------------- convenience snapshots ----------------

    def get_states(self) -> Dict[str, Optional[RobotState]]:
        return {"left": self.left.get_state(), "right": self.right.get_state()}

    def get_states_parallel(self) -> Dict[str, Optional[RobotState]]:
        """Read both arms' state concurrently on the persistent pool.

        On real hardware each ``get_state()`` is an 8–12 ms ZMQ REQ-REP
        round trip; running them serially in a 30 Hz teleop loop eats
        ~25 ms of the 33 ms budget. Two workers + one ZMQ socket per
        arm means there's no contention, so the wall-clock cost drops
        to roughly the max of the two ~ ~12 ms.
        """
        fl = self._pool.submit(self.left.get_state)
        fr = self._pool.submit(self.right.get_state)
        return {"left": fl.result(), "right": fr.result()}

    def get_joint_positions(self) -> Dict[str, Any]:
        return {
            "left":  self.left.get_joint_positions(),
            "right": self.right.get_joint_positions(),
        }

    def get_ee_positions(self) -> Dict[str, Any]:
        return {
            "left":  self.left.get_ee_position(),
            "right": self.right.get_ee_position(),
        }

    # ---------------- coordinated motion ----------------

    def _run_both(self, fn: Callable[[RobotService], Any]) -> Tuple[Any, Any]:
        """Run ``fn(self.left)`` and ``fn(self.right)`` in parallel threads.

        The two arms share a driver but write to disjoint per-arm ZMQ clients,
        so concurrent ``set_cmds`` from two threads doesn't fight (deque.append
        is thread-safe in CPython). Reuses the long-lived 2-worker pool
        instead of spinning up a fresh one each call.
        """
        fl = self._pool.submit(fn, self.left)
        fr = self._pool.submit(fn, self.right)
        return fl.result(), fr.result()

    def go_home(
        self,
        duration: Optional[float] = None,
        blocking: bool = True,
        home_position: Optional[np.ndarray] = None,
    ) -> bool:
        """Drive both arms to their home pose at the same time.

        With ``blocking=True`` both arm trajectories play in parallel threads
        and the call returns only after both complete.

        ``blocking=False`` only kicks off the first command of each trajectory
        (the underlying ``execute_trajectory`` is not background-able), so the
        arms won't actually finish — exposed for parity with the single-arm
        API but not generally useful here.

        ``home_position`` (optional) overrides the configured home for both
        arms — both are identical hardware, so a single shared target applies.
        """
        if not blocking:
            ok_left  = self.left.go_home(duration=duration, blocking=False, home_position=home_position)
            ok_right = self.right.go_home(duration=duration, blocking=False, home_position=home_position)
            return ok_left and ok_right
        ok_left, ok_right = self._run_both(
            lambda svc: svc.go_home(duration=duration, blocking=True, home_position=home_position)
        )
        return ok_left and ok_right

    def stop(self) -> bool:
        """Stop both arms simultaneously (safety: prefer parallel)."""
        ok_left, ok_right = self._run_both(lambda svc: svc.stop())
        return ok_left and ok_right

    # ---------------- factory helper ----------------

    @classmethod
    def from_config(
        cls,
        config: Optional[Dict[str, Any]] = None,
        calibration_paths: Optional[Dict[str, str]] = None,
    ) -> "DualArmRobotService":
        """One-stop construction: build a shared driver + both per-arm services.

        Args:
            config: passed to both per-arm :class:`RobotService` instances.
                ``config["mode"]`` selects ``"sim"`` or ``"real"``.
            calibration_paths: optional ``{"left": path, "right": path}``
                with per-arm hand-eye calibration JSONs.
        """
        from ..drivers import DriverFactory

        cfg = config or {}
        mode = cfg.get("mode", "real")
        driver_config = {
            "sim":    cfg.get("sim",    {"ip": "127.0.0.1", "port": 12345}),
            "robot":  cfg.get("robot",  {}),  # RealRobotDriver supplies its own dual defaults
            "camera": cfg.get("camera", {}),
        }
        factory = DriverFactory(mode=mode, config=driver_config)
        shared_driver = factory.create_robot_driver()

        calib = calibration_paths or {}
        left = RobotService(
            config=cfg,
            robot_client=shared_driver,
            calibration_path=calib.get("left"),
            arm_name="left",
        )
        right = RobotService(
            config=cfg,
            robot_client=shared_driver,
            calibration_path=calib.get("right"),
            arm_name="right",
        )
        return cls(left=left, right=right)
