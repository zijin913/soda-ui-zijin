import abc
import numpy as np
import time

# 引入你提供的 MujocoManager (假设在同一个文件或已导入)
from mujoco_manager import MujocoManager
import mujoco


class RobotInterface(abc.ABC):
    """
    机器人的抽象基类。
    定义了仿真和真机必须共同遵守的接口标准。
    """

    def __init__(self, num_joints=7):
        self.num_joints = num_joints

    @abc.abstractmethod
    def get_state(self):
        """
        获取当前机器人状态。
        Return:
            dict: {
                "q": np.ndarray, (n_joints,) 位置
                "dq": np.ndarray, (n_joints,) 速度
                "tau": np.ndarray, (n_joints,) 力矩 (可选)
            }
        """
        pass

    @abc.abstractmethod
    def set_command(self, q, dq=None, tau=None, kp=None, kd=None):
        """
        统一的控制接口。对应物理机器人的 set_cmds。

        Args:
            q (np.ndarray): 目标位置 (Rad)
            dq (np.ndarray): 目标速度 (Rad/s), 默认为 0
            tau (np.ndarray): 前馈力矩 (Nm), 默认为 0
            kp (np.ndarray): 刚度系数, 默认为 0
            kd (np.ndarray): 阻尼系数, 默认为 0
        """
        pass

    @abc.abstractmethod
    def step(self):
        """
        执行一步。
        对于仿真：调用模拟器的 step。
        对于真机：通常用于维持控制频率（sleep）或空操作。
        """
        pass

    @abc.abstractmethod
    def reset(self):
        """重置机器人状态"""
        pass

    @abc.abstractmethod
    def get_rgb(self):
        """
        获取RGB图像。
        Return:
            np.ndarray: RGB图像 (H, W, 3) 或 None
        """
        pass

    @abc.abstractmethod
    def get_point_cloud(self):
        """
        获取点云数据。
        Return:
            np.ndarray: 点云 (N, 3) 或 None
        """
        pass


class SimRobot(RobotInterface):
    """
    MuJoCo 仿真机器人的具体实现。
    封装了你提供的 MujocoManager。
    """

    def __init__(
        self,
        urdf_path,
        enable_gui=True,
        num_joints=7,
        video_path=None,
        pointcloud_path=None,
    ):
        super().__init__(num_joints)
        # 初始化你提供的管理器
        self.sim_manager = MujocoManager(urdf_path, enable_gui)
        # 缓存关节名称列表，用于按顺序映射
        # 注意：这里假设 URDF 中的前 num_joints 个关节就是我们要控制的关节
        self.joint_names = [
            mujoco.mj_id2name(self.sim_manager.model, mujoco.mjtObj.mjOBJ_JOINT, i)
            for i in range(self.sim_manager.model.njnt)
        ][:num_joints]

        # 初始化RGB和点云数据源
        import cv2

        self.video_cap = None
        self.video_path = video_path
        self.pointcloud_data = None

        if video_path:
            self.video_cap = cv2.VideoCapture(video_path)

        if pointcloud_path:
            import os

            if os.path.exists(pointcloud_path):
                self.pointcloud_data = np.load(pointcloud_path)
            else:
                self.pointcloud_data = np.zeros((0, 3), dtype=np.float32)

    def get_state(self):
        # 调用 MujocoManager 的方法获取状态列表
        sim_states = self.sim_manager.get_joint_states()

        # 将列表转换为 numpy 数组，保证顺序与 num_joints 一致
        q = np.zeros(self.num_joints)
        dq = np.zeros(self.num_joints)
        tau = np.zeros(self.num_joints)

        # 这里的逻辑取决于 get_joint_states 返回的顺序是否固定
        # 假设 sim_states 的顺序就是 joint_id 顺序
        for i, state in enumerate(sim_states):
            if i >= self.num_joints:
                break
            q[i] = state["angle"]
            dq[i] = state["velocity"]
            tau[i] = state["torque"]

        return {"q": q, "dq": dq, "tau": tau}

    def set_command(self, q, dq=None, tau=None, kp=None, kd=None):
        """
        MuJoCo 的实现逻辑。
        注意：你提供的 MujocoManager 目前只实现了 set_joint_target (位置控制)。
        如果需要支持力矩或阻抗控制，需要修改 MujocoManager 的底层 step 逻辑。
        目前这里只映射位置 q。
        """
        if len(q) != self.num_joints:
            raise ValueError(f"Command dimension mismatch: expected {self.num_joints}, got {len(q)}")

        # 将 numpy 数组映射回 MujocoManager 需要的 {id: angle} 格式
        # 或者直接调用 set_joint_target_by_name
        for i, target_angle in enumerate(q):
            # 方式1: 按索引·
            self.sim_manager.set_joint_target(i, target_angle)

            # 方式2 (更安全): 按名称
            # name = self.joint_names[i]
            # self.sim_manager.set_joint_target_by_name(name, target_angle)

    def step(self):
        # 仿真器推进一步
        self.sim_manager.step()

    def reset(self):
        self.sim_manager.reset()

    def get_rgb(self):
        """
        从视频文件读取RGB图像。
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
        返回缓存的点云数据。
        """
        return self.pointcloud_data


class RealRobot(RobotInterface):
    """
    物理机器人的具体实现，基于Hex机器人SDK。
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
            # 模式 3: 完整控制 (N, 5) -> [pos, vel, torque, kp, kd]
            cmds = np.column_stack([q, dq, tau, kp, kd])

        elif tau is not None:
            # 模式 2: 位置 + 力矩 (N, 2) -> [pos, torque]
            cmds = np.column_stack([q, tau])

        else:
            # 模式 1: 仅位置 (N,)
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
