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
        num_joints=None,
        video_path=None,
        pointcloud_path=None,
    ):
        # 初始化你提供的管理器
        self.sim_manager = MujocoManager(urdf_path, enable_gui)
        
        if num_joints is None:
            num_joints = self.sim_manager.model.njnt
        super().__init__(num_joints)
        
        # 缓存关节名称和ID，用于快速访问
        self.joint_names = [
            mujoco.mj_id2name(self.sim_manager.model, mujoco.mjtObj.mjOBJ_JOINT, i)
            for i in range(self.sim_manager.model.njnt)
        ][:num_joints]
        
        # 2. 夹爪相关 ID 初始化 (根据 XML 定义)
        self.gripper_driver_name = "gripper_left_joint_1"
        self.gripper_driver_idx = -1
        
        # 查找驱动关节在控制向量 q 中的索引
        if self.gripper_driver_name in self.joint_names:
            self.gripper_driver_idx = self.joint_names.index(self.gripper_driver_name)
        
        # 获取指尖 Link 的 Body ID，用于计算距离
        self.left_finger_body_id = mujoco.mj_name2id(
            self.sim_manager.model, mujoco.mjtObj.mjOBJ_BODY, "gripper_left_link_2"
        )
        self.right_finger_body_id = mujoco.mj_name2id(
            self.sim_manager.model, mujoco.mjtObj.mjOBJ_BODY, "gripper_right_link_2"
        )

        # 3. 初始化夹爪 距离-角度 映射表 (LUT)
        if self.gripper_driver_idx != -1 and self.left_finger_body_id >= 0:
            self._init_gripper_lut()
        else:
            print("Warning: Gripper joints/links not found. Gripper control disabled.")
            self.dist_table = None
            self.angle_table = None

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

    def _init_gripper_lut(self):
        """
        在初始化阶段构建 距离<->角度 的查找表。
        这样 set_gripper_distance 就是 O(1) 操作，且不需要 step 仿真。
        """
        model = self.sim_manager.model
        data = self.sim_manager.data
        
        # 找出所有的 mimic 关节 ID（包括驱动关节本身）
        # XML 中定义的 mimic 关系是 1.0 倍率
        mimic_joint_names = [
            "gripper_left_joint_1",   # Driver
            "gripper_left_joint_2",   # Mimic
            "gripper_left_helper_joint",
            "gripper_right_joint_1",  # Mimic
            "gripper_right_joint_2",  # Mimic
            "gripper_right_helper_joint"
        ]
        
        # 获取这些关节在 MuJoCo qpos 数组中的地址 (qpos_adr)
        mimic_adrs = []
        for name in mimic_joint_names:
            jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            if jid >= 0:
                mimic_adrs.append(model.jnt_qposadr[jid])

        # 驱动关节范围 (从 XML limit 读取: 0 ~ 1.52)
        # 为了更精确，可以读取 model.jnt_range
        driver_jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, self.gripper_driver_name)
        min_angle, max_angle = model.jnt_range[driver_jid]
        
        # 备份当前状态
        backup_qpos = data.qpos.copy()
        
        num_points = 50
        self.angle_table = np.linspace(min_angle, max_angle, num_points)
        self.dist_table = np.zeros(num_points)
        
        # 遍历角度，仅进行运动学解算 (Kinematics)，不进行动力学步进 (Step)
        for i, angle in enumerate(self.angle_table):
            # 手动设置所有相关关节的角度（模拟 mimic 行为）
            # 因为 mj_kinematics 是纯几何计算，不会自动处理 constraint，需要手动赋值
            for adr in mimic_adrs:
                data.qpos[adr] = angle  # 假设 multiplier=1.0, offset=0
            
            # 更新几何位置
            mujoco.mj_kinematics(model, data)
            
            # 计算距离
            pos_l = data.xpos[self.left_finger_body_id]
            pos_r = data.xpos[self.right_finger_body_id]
            self.dist_table[i] = np.linalg.norm(pos_l - pos_r)
            
        # 恢复状态
        data.qpos[:] = backup_qpos
        mujoco.mj_kinematics(model, data)
        
        # 确保 distance 是单调的（通常是的），以便 np.interp 使用
        # 打印调试信息：print(f"Gripper range: {self.dist_table[0]:.4f}m (Open) -> {self.dist_table[-1]:.4f}m (Closed)")

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
            raise ValueError(
                f"Command dimension mismatch: expected {self.num_joints}, got {len(q)}"
            )

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

    def get_gripper_distance(self):
        """
        获取当前夹爪距离。
        """
        # 确保数据是最新的
        # 注意：通常 step() 后会自动更新，但如果只控制没 step，可能需要 mj_kinematics
        # 这里假设外部循环会调用 step()
        
        left_pos = self.sim_manager.data.xpos[self.left_finger_body_id]
        right_pos = self.sim_manager.data.xpos[self.right_finger_body_id]
        
        return np.linalg.norm(left_pos - right_pos)

    def set_gripper_distance(self, distance):
        """
        设置夹爪目标距离。
        注意：这会修改当前的控制指令。
        """
        if self.dist_table is None or self.gripper_driver_idx == -1:
            return

        # 1. 限制距离范围
        # 由于插值不会外推，我们需要确保输入在表格范围内
        # 注意 dist_table 可能是递减的（角度越大，距离越小）
        min_d = min(self.dist_table)
        max_d = max(self.dist_table)
        distance = np.clip(distance, min_d, max_d)

        # 2. 查表计算目标角度 (Linear Interpolation)
        # np.interp 要求 x 坐标 (self.dist_table) 是递增的
        if self.dist_table[0] < self.dist_table[-1]:
            target_angle = np.interp(distance, self.dist_table, self.angle_table)
        else:
            # 如果距离随角度减小 (常见的夹爪)，需要翻转数组进行插值
            target_angle = np.interp(distance, self.dist_table[::-1], self.angle_table[::-1])

        # 3. 设置指令
        # 获取当前的完整关节指令（保持手臂不动，只动夹爪）
        # 这里假设我们应该维持当前的实际位置作为手臂的目标，或者你需要维护一个类内的 self.current_target
        current_state = self.get_state()
        target_q = current_state["q"].copy()
        
        # 更新夹爪驱动关节的目标角度
        target_q[self.gripper_driver_idx] = target_angle
        
        # 发送指令
        self.set_command(target_q)


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
