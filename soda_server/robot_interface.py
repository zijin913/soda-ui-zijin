import abc
import numpy as np
import time

from mujoco_manager import MujocoManager
import mujoco


class RobotInterface(abc.ABC):
    """
    Abstract base class for robots.
    Defines the common interface that both simulation and real hardware must follow.
    """

    def __init__(self, num_joints=7):
        self.num_joints = num_joints

    @abc.abstractmethod
    def get_state(self):
        """
        Get the current robot state.
        Return:
            dict: {
                "q": np.ndarray, (n_joints,) position
                "dq": np.ndarray, (n_joints,) velocity
                "tau": np.ndarray, (n_joints,) torque (optional)
            }
        """
        pass

    @abc.abstractmethod
    def set_command(self, q, dq=None, tau=None, kp=None, kd=None):
        """
        Unified control interface. Maps to set_cmds on the physical robot.

        Args:
            q (np.ndarray): target position (Rad)
            dq (np.ndarray): target velocity (Rad/s), defaults to 0
            tau (np.ndarray): feedforward torque (Nm), defaults to 0
            kp (np.ndarray): stiffness coefficient, defaults to 0
            kd (np.ndarray): damping coefficient, defaults to 0
        """
        pass

    @abc.abstractmethod
    def step(self):
        """
        Execute one step.
        For simulation: calls the simulator's step.
        For real hardware: typically used to maintain control rate (sleep) or as a no-op.
        """
        pass

    @abc.abstractmethod
    def reset(self):
        """Reset the robot state"""
        pass

    @abc.abstractmethod
    def get_rgb(self):
        """
        Get an RGB image.
        Return:
            np.ndarray: RGB image (H, W, 3) or None
        """
        pass

    @abc.abstractmethod
    def get_point_cloud(self):
        """
        Get point cloud data.
        Return:
            np.ndarray: point cloud (N, 3) or None
        """
        pass


class SimRobot(RobotInterface):
    """
    Concrete implementation of the MuJoCo simulation robot.
    Wraps MujocoManager.
    """

    def __init__(
        self,
        urdf_path,
        enable_gui=True,
        num_joints=None,
        video_path=None,
        pointcloud_path=None,
    ):
        self.sim_manager = MujocoManager(urdf_path, enable_gui)

        if num_joints is None:
            num_joints = self.sim_manager.model.njnt
        super().__init__(num_joints)

        # Cache joint names and IDs for fast access
        self.joint_names = [
            mujoco.mj_id2name(self.sim_manager.model, mujoco.mjtObj.mjOBJ_JOINT, i)
            for i in range(self.sim_manager.model.njnt)
        ][:num_joints]

        # Gripper ID initialization (per the XML definition)
        self.gripper_driver_name = "gripper_left_joint_1"
        self.gripper_driver_idx = -1

        # Find the driver joint's index in the control vector q
        if self.gripper_driver_name in self.joint_names:
            self.gripper_driver_idx = self.joint_names.index(self.gripper_driver_name)

        # Fingertip link body IDs, used to compute the gripper distance
        self.left_finger_body_id = mujoco.mj_name2id(
            self.sim_manager.model, mujoco.mjtObj.mjOBJ_BODY, "gripper_left_link_2"
        )
        self.right_finger_body_id = mujoco.mj_name2id(
            self.sim_manager.model, mujoco.mjtObj.mjOBJ_BODY, "gripper_right_link_2"
        )

        # Initialize the gripper distance-to-angle lookup table (LUT)
        if self.gripper_driver_idx != -1 and self.left_finger_body_id >= 0:
            self._init_gripper_lut()
        else:
            print("Warning: Gripper joints/links not found. Gripper control disabled.")
            self.dist_table = None
            self.angle_table = None

        # Initialize RGB and point cloud data sources
        import cv2

        self.video_cap = None
        self.video_path = video_path
        self.pointcloud_data = None

        if video_path:
            self.video_cap = cv2.VideoCapture(video_path)

        if pointcloud_path:
            import os

            if os.path.exists(pointcloud_path):
                # Only take the first 3 columns (XYZ) and ensure float32
                full_data = np.load(pointcloud_path)
                self.pointcloud_data = full_data[:, :3].astype(np.float32)
            else:
                self.pointcloud_data = np.zeros((0, 3), dtype=np.float32)

    def _init_gripper_lut(self):
        """
        Build the distance<->angle lookup table at init time, so that
        set_gripper_distance is O(1) and does not require stepping the sim.
        """
        model = self.sim_manager.model
        data = self.sim_manager.data

        # All mimic joint IDs (including the driver joint itself).
        # The mimic relations defined in the XML use a 1.0 multiplier.
        mimic_joint_names = [
            "gripper_left_joint_1",   # Driver
            "gripper_left_joint_2",   # Mimic
            "gripper_left_helper_joint",
            "gripper_right_joint_1",  # Mimic
            "gripper_right_joint_2",  # Mimic
            "gripper_right_helper_joint"
        ]
        
        # Addresses of these joints in the MuJoCo qpos array (qpos_adr)
        mimic_adrs = []
        for name in mimic_joint_names:
            jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            if jid >= 0:
                mimic_adrs.append(model.jnt_qposadr[jid])

        # Driver joint range (read from XML limit: 0 ~ 1.52); read model.jnt_range for precision
        driver_jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, self.gripper_driver_name)
        min_angle, max_angle = model.jnt_range[driver_jid]

        # Back up the current state
        backup_qpos = data.qpos.copy()

        num_points = 50
        self.angle_table = np.linspace(min_angle, max_angle, num_points)
        self.dist_table = np.zeros(num_points)

        # Sweep angles using kinematics only, without dynamics stepping
        for i, angle in enumerate(self.angle_table):
            # Manually set all related joint angles (emulating mimic behavior),
            # because mj_kinematics is pure geometry and does not resolve constraints.
            for adr in mimic_adrs:
                data.qpos[adr] = angle  # assumes multiplier=1.0, offset=0

            mujoco.mj_kinematics(model, data)

            pos_l = data.xpos[self.left_finger_body_id]
            pos_r = data.xpos[self.right_finger_body_id]
            self.dist_table[i] = np.linalg.norm(pos_l - pos_r)

        # Restore the state
        data.qpos[:] = backup_qpos
        mujoco.mj_kinematics(model, data)

        # distance should be monotonic (usually is) so np.interp can use it

    def get_state(self):
        sim_states = self.sim_manager.get_joint_states()

        q = np.zeros(self.num_joints)
        dq = np.zeros(self.num_joints)
        tau = np.zeros(self.num_joints)

        # Assumes sim_states is ordered by joint_id, matching num_joints order
        for i, state in enumerate(sim_states):
            if i >= self.num_joints:
                break
            q[i] = state["angle"]
            dq[i] = state["velocity"]
            tau[i] = state["torque"]

        return {"q": q, "dq": dq, "tau": tau}

    def set_command(self, q, dq=None, tau=None, kp=None, kd=None):
        """
        MuJoCo implementation.
        Note: MujocoManager currently only implements set_joint_target (position control).
        Supporting torque or impedance control requires changing MujocoManager's
        underlying step logic. For now this only maps position q.
        """
        if len(q) != self.num_joints:
            raise ValueError(
                f"Command dimension mismatch: expected {self.num_joints}, got {len(q)}"
            )

        # Map the numpy array back to the {id: angle} format MujocoManager expects
        for i, target_angle in enumerate(q):
            # Option 1: by index
            self.sim_manager.set_joint_target(i, target_angle)

            # Option 2 (safer): by name
            # name = self.joint_names[i]
            # self.sim_manager.set_joint_target_by_name(name, target_angle)

    def step(self):
        self.sim_manager.step()

    def reset(self):
        self.sim_manager.reset()

    def get_rgb(self):
        """
        Read an RGB image from the video file.
        """
        if self.video_cap is None:
            return None

        import cv2

        ret, frame = self.video_cap.read()
        if not ret:
            self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.video_cap.read()

        if ret and frame is not None:
            frame = cv2.resize(frame, (640, 360))
            return frame
        return None

    def get_point_cloud(self):
        """
        Return the cached point cloud data.
        """
        return self.pointcloud_data

    def get_gripper_distance(self):
        """
        Get the current gripper distance.
        """
        # Assumes the outer loop calls step(). xpos is normally refreshed after
        # step(); if you command without stepping, mj_kinematics may be needed.
        left_pos = self.sim_manager.data.xpos[self.left_finger_body_id]
        right_pos = self.sim_manager.data.xpos[self.right_finger_body_id]
        
        return np.linalg.norm(left_pos - right_pos)

    def set_gripper_distance(self, distance):
        """
        Set the target gripper distance.
        Note: this modifies the current control command.
        """
        if self.dist_table is None or self.gripper_driver_idx == -1:
            return

        # Clamp the distance: interpolation does not extrapolate, so the input
        # must stay within the table range. dist_table may be decreasing
        # (larger angle -> smaller distance).
        min_d = min(self.dist_table)
        max_d = max(self.dist_table)
        distance = np.clip(distance, min_d, max_d)

        # Look up the target angle (linear interpolation).
        # np.interp requires the x coordinates (self.dist_table) to be increasing.
        if self.dist_table[0] < self.dist_table[-1]:
            target_angle = np.interp(distance, self.dist_table, self.angle_table)
        else:
            # If distance decreases with angle (typical gripper), reverse the arrays to interpolate
            target_angle = np.interp(distance, self.dist_table[::-1], self.angle_table[::-1])

        # Use the current full joint state as the target so the arm stays put and only the gripper moves
        current_state = self.get_state()
        target_q = current_state["q"].copy()

        target_q[self.gripper_driver_idx] = target_angle

        self.set_command(target_q)


class RealRobot(RobotInterface):
    """
    Concrete implementation of the physical robot, based on the Hex robot SDK.
    """

    def __init__(self, net_config_json, num_joints=7):
        super().__init__(num_joints)
        import json

        net_config = json.loads(net_config_json)
        from hex_zmq_servers import HexRobotHexarmClient

        self.robot = HexRobotHexarmClient(net_config=net_config)
        self.num_joints = self.robot.get_dofs()[0]

    def get_state(self):
        states_hdr, states = self.robot.get_states()
        if states_hdr is None:
            return {
                "q": np.zeros(self.num_joints),
                "dq": np.zeros(self.num_joints),
                "tau": np.zeros(self.num_joints),
            }
        return {"q": states[:, 0], "dq": states[:, 1], "tau": states[:, 2]}

    def set_command(self, q, dq=None, tau=None, kp=None, kd=None):
        if dq is not None and tau is not None and kp is not None and kd is not None:
            # Mode 3: full control (N, 5) -> [pos, vel, torque, kp, kd]
            cmds = np.column_stack([q, dq, tau, kp, kd])

        elif tau is not None:
            # Mode 2: position + torque (N, 2) -> [pos, torque]
            cmds = np.column_stack([q, tau])

        else:
            # Mode 1: position only (N,)
            cmds = np.array(q)
        self.robot.set_cmds(cmds)

    def step(self):
        pass

    def reset(self):
        pass

    def get_rgb(self):
        return None

    def get_point_cloud(self):
        return None
