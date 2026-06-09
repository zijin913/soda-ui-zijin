"""
Quest VIO Controller — 6-DOF teleoperation via Meta Quest 3 controller.

Structurally aligned 1:1 with IPhoneVIOController: reset() / get_action(obs) /
set_mode / toggle_gripper / set_position_scale / recenter / get_info / close.

The only differences are:
    (1) the coordinate-frame remap matrix (Quest controller frame → HexArm base)
    (2) buttons are read from QuestReader (same tuple (T, ts, count, gripper, clutch, home))
    (3) the class name is written into the h5 attrs["controller"] by
        trajectory_recorder, so iPhone / Quest trajectories are distinguished
        automatically

First-time calibration procedure (TELEOP_QUEST.md has a more detailed writeup):
    1. Stand directly in front of the arm, wearing the headset
    2. Hold the trigger (clutch) and move the controller 1m "forward" (away from you)
    3. Observe which axis the EE travels along in the arm's base frame
    4. Adjust the row permutation of R_REMAP_QUEST until forward/back,
       left/right and up/down all line up

The defaults are a reasonable starting point for "headset facing HexArm +X,
headset +Y up, -Z forward", but you'll almost certainly have to tune them once
the hardware layout changes.
"""

import time
import numpy as np
from scipy.spatial.transform import Rotation as RotScipy
from typing import Optional, Dict, Any

from .base import Controller


# ─── Default coordinate map (Quest controller frame → HexArm base frame) ──────
# Quest: +X right, +Y up, -Z forward (headset-local at APK startup)
# HexArm base: +X forward (operator facing direction), +Y left, +Z up
# Default: Quest (-Z forward) → HexArm (+X forward); Quest (+X right) → HexArm (-Y);
#          Quest (+Y up) → HexArm (+Z up)
R_REMAP_QUEST_DEFAULT = np.array(
    [[0, 0, -1],
     [-1, 0, 0],
     [0, 1, 0]],
    dtype=np.float64,
)
# Secondary rotation-correction matrix, identity by default; tune after
# calibration if there's pitch/yaw cross-coupling.
R_CORR_QUEST_DEFAULT = np.eye(3, dtype=np.float64)

# Per-axis rotation sign flip (applied in the HexArm base frame, after the
# similarity transform). Each element ∈ {-1, +1}, corresponding to the rotation
# direction of [roll(X), pitch(Y), yaw(Z)].
# Even after R_remap maps Quest coordinates into the HexArm base frame as a
# valid rotation (det=+1), the "positive direction" of each axis still depends
# on operator habit (left/right, clockwise/counter-clockwise). These three
# independent sign-flip switches align the rotation to user preference.
# Default: flip roll and yaw (handles the counter-intuitive case where swinging
# the controller left/right would otherwise rotate the EE the opposite way).
ROT_SIGN_FLIP_DEFAULT = np.array([-1.0, 1.0, -1.0], dtype=np.float64)


# ─── Helpers (kept in sync with iphone_vio.py to share tests) ─────────────────
def _orthogonalize(R):
    U, _, Vt = np.linalg.svd(R)
    R_orth = U @ Vt
    if np.linalg.det(R_orth) < 0:
        U[:, -1] *= -1
        R_orth = U @ Vt
    return R_orth


def _rot_to_quat(R):
    import pinocchio as pin
    q = pin.Quaternion(_orthogonalize(R))
    return np.array([q.w, q.x, q.y, q.z])


def _interp_joint(cur_q, tar_q, err_limit):
    err = tar_q - cur_q
    max_err = np.fabs(err).max()
    if max_err < err_limit:
        return tar_q.copy(), False
    return cur_q + (err / max_err) * err_limit, True


class QuestVIOController(Controller):
    """
    6-DOF teleoperation using the Meta Quest 3 controller.

    Integrated the same way as IPhoneVIOController: collect_demos.py only needs
    to call get_action().
    """

    def __init__(
        self,
        solver,
        vio_receiver,
        home_joints: np.ndarray = None,
        joint_lower: np.ndarray = None,
        joint_upper: np.ndarray = None,
        # ── Tunable parameters (@100Hz real teleop via collect_demos) ──
        position_scale: float = 0.7,       # 1:0.7, good tracking
        smooth_alpha: float = 0.15,        # time constant ~70ms (was 0.05 = 200ms)
        pos_deadzone: float = 0.002,
        rot_deadzone: float = 0.07,
        interp_err_limit: float = 0.015,   # 86°/s max joint velocity (was 0.01 = 57°/s)
        dropout_timeout: float = 0.5,
        # Safety: never let the COMMAND lead the OBSERVED joint by more than
        # this (rad/joint). Bounds the worst-case jump if commands transiently
        # don't reach the arm (e.g. seq desync) — the controller otherwise keeps
        # integrating Quest motion into _last_cmd_q while the arm is frozen.
        # 0 = disabled.
        lead_cap: float = 0.30,
        # ── Gripper parameters ──
        gripper_open: float = 0.0,
        gripper_close: float = 1.33,
        # ── Quest-specific coordinate remap (can be injected externally) ──
        R_remap: np.ndarray = None,
        R_corr: np.ndarray = None,
        rot_sign_flip: np.ndarray = None,
    ):
        """
        Args:
            solver: HexDynUtilL6Y instance (FK + IK)
            vio_receiver: QuestReader instance (ADB pose reader)
            home_joints: home joint configuration (6,)
            joint_lower/upper: joint limits (6,)
            position_scale: Quest displacement → robot displacement scale
            smooth_alpha: low-pass filter (0=frozen, 1=no filter)
            pos_deadzone: ignore position changes smaller than this (meters)
            rot_deadzone: ignore rotations smaller than this (radians)
            interp_err_limit: max joint change per step (rad)
            dropout_timeout: freeze after this many seconds without VIO data
            gripper_open/gripper_close: gripper joint angles
            R_remap: 3x3, Quest controller frame → HexArm base frame; defaults to R_REMAP_QUEST_DEFAULT
            R_corr: 3x3, secondary rotation correction (defaults to identity)
            rot_sign_flip: (3,) array, each entry ∈ {-1, +1}, applies a per-axis
                sign flip to the [roll, pitch, yaw] rotation direction in the
                HexArm frame after the similarity transform. Defaults to
                [-1, 1, -1] to fix the roll/yaw reversal caused by the current
                R_remap having det=-1.
        """
        self.solver = solver
        self.vio = vio_receiver

        self.home_joints = home_joints if home_joints is not None else \
            np.array([0.0, -0.785, 2.2, 0.5, 0.0, 0.0])
        self.joint_lower = joint_lower if joint_lower is not None else \
            np.array([-2.86, -2.09, 0.0, -1.57, -1.57, -3.14])
        self.joint_upper = joint_upper if joint_upper is not None else \
            np.array([2.86, 1.57, 3.16, 1.57, 1.57, 3.14])

        self.position_scale = position_scale
        self.smooth_alpha = smooth_alpha
        self.pos_deadzone = pos_deadzone
        self.rot_deadzone = rot_deadzone
        self.interp_err_limit = interp_err_limit
        self.dropout_timeout = dropout_timeout
        self.lead_cap = lead_cap
        self.gripper_open = gripper_open
        self.gripper_close = gripper_close

        self.R_remap = np.asarray(R_remap if R_remap is not None else R_REMAP_QUEST_DEFAULT,
                                  dtype=np.float64)
        self.R_corr = np.asarray(R_corr if R_corr is not None else R_CORR_QUEST_DEFAULT,
                                 dtype=np.float64)
        self.rot_sign_flip = np.asarray(
            rot_sign_flip if rot_sign_flip is not None else ROT_SIGN_FLIP_DEFAULT,
            dtype=np.float64,
        )

        # Precompute home EE pose
        from hex_robo_utils import part2trans
        home_fk = solver.forward_kinematics(self.home_joints)
        self.home_pos, self.home_quat = home_fk[-1]
        self._T_home_ee = part2trans(self.home_pos, self.home_quat)

        # State (initialized in reset())
        self._reset_state()

        # Sub-timing buckets (persist across episodes; printed in close())
        self._sub_times: Dict[str, list] = {
            "vio": [], "pre_ik": [], "ik": [], "gripper_interp": []}

    def _reset_state(self):
        self._T_quest_ref = None
        self._T_quest_ref_inv = None
        self._clutch_base_T = self._T_home_ee.copy()
        self._tar_joint = self.home_joints.copy()
        self._tar_pos = self.home_pos.copy()
        self._tar_quat = self.home_quat.copy()
        self._smooth_pos = self.home_pos.copy()
        self._smooth_quat = self.home_quat.copy()
        self._last_cmd_q = np.zeros(7)
        self._last_cmd_q[:6] = self.home_joints
        self._last_cmd_q[6] = self.gripper_open
        self._grip_flag = False
        self._last_recv_count = 0
        self._last_recv_time = time.time()
        self._was_clutch = False
        # Quest home-button rising-edge tracking. ``_home_press_event`` is
        # latched True for one main-loop tick after the button transitions
        # from up → down, so the teleop main loop can pick it up and route
        # to ``dual.go_home(duration=...)`` for a slow, smooth return
        # instead of the immediate target-snap below (which only relies
        # on ``_interp_joint``'s per-tick rate cap and races back to home).
        self._was_home = False
        self._home_press_event = False
        self._mode = "both"  # "both", "pos", "rot"
        self._success = False
        self._failure = False
        self._frame_count = 0

    def reset(self) -> None:
        self._reset_state()

    def get_action(self, observation: dict) -> Optional[dict]:
        """
        Compute an action from the observation + latest Quest data. The single
        entry point for the control logic.
        """
        from hex_robo_utils import part2trans
        now = observation.get("timestamp", time.time())
        _t0 = time.perf_counter_ns()

        # ── 1. Read Quest VIO ──
        T_quest, vio_ts, vio_count, vio_gripper, vio_clutch, vio_home = self.vio.get_pose()
        _t_vio = time.perf_counter_ns()

        if T_quest is None:
            return None

        if vio_count > self._last_recv_count:
            self._last_recv_count = vio_count
            self._last_recv_time = now

            # HOME button (A / X): rising-edge → signal main loop to run
            # a slow ``dual.go_home`` trajectory. The internal snap below
            # still runs as a fallback (e.g. sim-only / no main-loop
            # interception), but its motion is rate-limited by
            # ``_interp_joint`` which is too aggressive for a real
            # "return home" action — the main loop's blocking
            # ``go_home(duration=...)`` is the preferred path.
            self._home_press_event = bool(vio_home and not self._was_home)
            self._was_home = bool(vio_home)
            if vio_home:
                self._tar_pos = self.home_pos.copy()
                self._tar_quat = self.home_quat.copy()
                self._smooth_pos = self.home_pos.copy()
                self._smooth_quat = self.home_quat.copy()
                self._clutch_base_T = self._T_home_ee.copy()
                self._tar_joint = self.home_joints.copy()

            # Clutch state change
            if vio_clutch and not self._was_clutch:
                # Just pressed → reset the Quest reference + use the current EE as base.
                # Re-anchor to the ACTUAL observed joint pose (not the internal
                # _last_cmd_q, which may have drifted from the arm if earlier
                # commands didn't land) so a clutch press NEVER jumps.
                obs_q = observation.get("joint_positions")
                if obs_q is not None and len(obs_q) >= 6:
                    self._last_cmd_q[:6] = np.asarray(obs_q[:6], dtype=np.float64)
                    if len(obs_q) > 6:
                        self._last_cmd_q[6] = float(obs_q[6])
                self._T_quest_ref = T_quest.copy()
                self._T_quest_ref_inv = np.linalg.inv(T_quest)
                cur_fk_pos, cur_fk_quat = self.solver.forward_kinematics(self._last_cmd_q[:6])[-1]
                self._clutch_base_T = part2trans(cur_fk_pos, cur_fk_quat)
                # Align target/smoothed pose to the same anchor so the first
                # IK step starts exactly here (zero initial delta → no jump).
                self._tar_pos = cur_fk_pos.copy()
                self._tar_quat = cur_fk_quat.copy()
                self._smooth_pos = cur_fk_pos.copy()
                self._smooth_quat = cur_fk_quat.copy()
                if self._frame_count > 0:
                    print(f"  >>> Clutch ON")
            elif not vio_clutch and self._was_clutch:
                print(f"  >>> Clutch OFF")
            self._was_clutch = vio_clutch

            # Only compute the delta while the clutch is engaged
            if vio_clutch and self._T_quest_ref is not None:
                delta_T = self._T_quest_ref_inv @ T_quest
                delta_pos_quest = delta_T[:3, 3]
                delta_rot_quest = delta_T[:3, :3]

                # Position mapping
                cur_delta_pos = self.R_remap @ delta_pos_quest * self.position_scale

                # Rotation mapping
                delta_rot_corrected = self.R_corr @ delta_rot_quest @ self.R_corr.T
                mapped = self.R_remap @ delta_rot_corrected @ self.R_remap.T
                # Per-axis sign flip (roll/pitch/yaw in the HexArm base frame).
                # When det(R_remap)=-1 the similarity transform flips some
                # rotation directions; this corrects them back.
                rotvec = RotScipy.from_matrix(mapped).as_rotvec() * self.rot_sign_flip
                cur_delta_rot = RotScipy.from_rotvec(rotvec).as_matrix()

                # Dead zones
                if np.linalg.norm(delta_pos_quest) < self.pos_deadzone:
                    cur_delta_pos = np.zeros(3)
                rot_angle = np.arccos(np.clip((np.trace(delta_rot_quest) - 1) / 2, -1, 1))
                if rot_angle < self.rot_deadzone:
                    cur_delta_rot = np.eye(3)

                # Apply delta
                if self._mode in ("both", "pos"):
                    self._tar_pos = self._clutch_base_T[:3, 3] + cur_delta_pos
                if self._mode in ("both", "rot"):
                    tar_rot = self._clutch_base_T[:3, :3] @ cur_delta_rot
                    self._tar_quat = _rot_to_quat(tar_rot)

        elif (now - self._last_recv_time) > self.dropout_timeout:
            # Data dropout — return None to make the main loop freeze
            if self._frame_count % 500 == 0:
                print(f"  [!] Quest data lost {now - self._last_recv_time:.1f}s")
            self._frame_count += 1
            return None

        # ── 2. Low-pass filter ──
        a = self.smooth_alpha
        self._smooth_pos = self._smooth_pos * (1 - a) + self._tar_pos * a
        self._smooth_quat = self._smooth_quat * (1 - a) + self._tar_quat * a
        self._smooth_quat /= np.linalg.norm(self._smooth_quat)

        # ── 3. IK solve ──
        _t_pre_ik = time.perf_counter_ns()
        ik_success, ik_q = self.solver.inverse_kinematics_analytic(
            (self._smooth_pos, self._smooth_quat), self._last_cmd_q[:6])

        if not ik_success:
            # max_iter=20 caps the worst-case fallback at ~25ms; analytic covers
            # the common case in <1ms. With max_iter=50 we saw 58ms outliers.
            ik_success_num, ik_q_num, _ = self.solver.inverse_kinematics(
                (self._smooth_pos, self._smooth_quat), self._last_cmd_q[:6], max_iter=20)
            if ik_success_num:
                ik_success = True
                ik_q = ik_q_num

        if ik_success:
            self._tar_joint = np.clip(ik_q, self.joint_lower, self.joint_upper)
        else:
            # IK failed → snap back to the current FK
            self._tar_pos, self._tar_quat = self.solver.forward_kinematics(self._last_cmd_q[:6])[-1]
            self._smooth_pos = self._tar_pos.copy()
            self._smooth_quat = self._tar_quat.copy()
        _t_post_ik = time.perf_counter_ns()

        # ── 4. Gripper ──
        if self._grip_flag:
            grip_val = self.gripper_close
        else:
            grip_val = self.gripper_open + vio_gripper * (self.gripper_close - self.gripper_open)

        # ── 5. Speed-limited interpolation ──
        mid_joint = np.zeros(7)
        mid_joint[:6], _ = _interp_joint(self._last_cmd_q[:6], self._tar_joint, self.interp_err_limit)
        mid_joint[6], _ = _interp_joint(
            np.array([self._last_cmd_q[6]]), np.array([grip_val]), self.interp_err_limit)

        # Anti-runaway clamp: never let the command lead the OBSERVED joint by
        # more than ``lead_cap`` rad. If the arm isn't tracking (commands not
        # landing), this stops _last_cmd_q from integrating far ahead, so when
        # control resumes the arm can't make a large accumulated jump.
        if self.lead_cap > 0:
            obs_q = observation.get("joint_positions")
            if obs_q is not None and len(obs_q) >= 6:
                obs6 = np.asarray(obs_q[:6], dtype=np.float64)
                mid_joint[:6] = np.clip(mid_joint[:6], obs6 - self.lead_cap, obs6 + self.lead_cap)

        self._last_cmd_q = mid_joint.copy()

        # FK is no longer computed here — caller computes it on record frames
        # only (cartesian_position is purely a recording artifact).
        _t_post_ctrl = time.perf_counter_ns()

        self._frame_count += 1

        # ── 7. Status print ──
        if self._frame_count % 100 == 0:
            dp = self._tar_pos - self._T_home_ee[:3, 3]
            print(f"  [{self._mode:4s}] scale={self.position_scale:.1f}x  "
                  f"delta=[{dp[0]:+.3f} {dp[1]:+.3f} {dp[2]:+.3f}]m  "
                  f"IK:{'OK' if ik_success else 'FAIL'}  "
                  f"grip={vio_gripper:.0%}→{grip_val:.2f}  "
                  f"clutch={'ON' if vio_clutch else 'OFF'}")

        self._sub_times["vio"].append(_t_vio - _t0)
        self._sub_times["pre_ik"].append(_t_pre_ik - _t_vio)
        self._sub_times["ik"].append(_t_post_ik - _t_pre_ik)
        self._sub_times["gripper_interp"].append(_t_post_ctrl - _t_post_ik)

        return {
            "joint_position": mid_joint[:6].copy(),
            "gripper_position": float(mid_joint[6]),
        }

    # ── Keyboard control methods (called by collect_demos.py) ──

    def set_mode(self, mode: str):
        assert mode in ("both", "pos", "rot")
        self._mode = mode

    def toggle_gripper(self):
        self._grip_flag = not self._grip_flag
        print(f"  >>> Gripper: {'close' if self._grip_flag else 'open'}")

    def set_position_scale(self, scale: float):
        self.position_scale = max(0.5, min(5.0, scale))
        print(f"  >>> Scale: {self.position_scale:.1f}x")

    def recenter(self):
        """Use the current Quest pose as the new reference and send the target back to home."""
        T_cur, _, _, _, _, _ = self.vio.get_pose()
        if T_cur is not None:
            self._T_quest_ref = T_cur.copy()
            self._T_quest_ref_inv = np.linalg.inv(T_cur)
            self._tar_pos = self.home_pos.copy()
            self._tar_quat = self.home_quat.copy()
            self._smooth_pos = self.home_pos.copy()
            self._smooth_quat = self.home_quat.copy()
            self._clutch_base_T = self._T_home_ee.copy()
            print(f"  >>> Recenter!")

    def mark_success(self):
        self._success = True

    def mark_failure(self):
        self._failure = True

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": "QuestVIOController",
            "controller_on": True,
            "movement_enabled": self._was_clutch,
            "success": self._success,
            "failure": self._failure,
            "mode": self._mode,
            "position_scale": self.position_scale,
            "clutch_active": self._was_clutch,
        }

    def close(self) -> None:
        # Report get_action sub-timings
        if self._sub_times.get("vio"):
            tag = getattr(self.vio, "hand", "?")
            print(f"\n  ── QuestVIOController({tag}) get_action sub-timings (ms) ──")
            print(f"  {'section':<8} {'n':>5} {'p50':>7} {'p95':>7} {'p99':>7} {'max':>7}")
            for name, vals in self._sub_times.items():
                if not vals:
                    continue
                arr = sorted(vals)
                n = len(arr)
                pick = lambda f: arr[min(int(n * f), n - 1)] / 1e6
                print(f"  {name:<8} {n:>5} {pick(0.50):>7.2f} {pick(0.95):>7.2f} "
                      f"{pick(0.99):>7.2f} {arr[-1] / 1e6:>7.2f}")
        self.vio.close()
