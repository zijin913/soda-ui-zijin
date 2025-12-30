import mujoco
import mujoco.viewer
import numpy as np
import os


class MujocoManager:
    def __init__(self, urdf_path, enable_gui=True):
        self.urdf_path = urdf_path
        urdf_abs_path = os.path.abspath(urdf_path)
        urdf_dir = os.path.dirname(urdf_abs_path)

        orig_cwd = os.getcwd()

        try:
            os.chdir(urdf_dir)
            self.model = mujoco.MjModel.from_xml_path(urdf_abs_path)
            self.data = mujoco.MjData(self.model)
            print(f"MuJoCo model loaded: {self.model.njnt} joints, {self.model.ngeom} geoms, {self.model.nmesh} meshes")

            self.joint_commands = {}
            self.paused = False
            self.viewer = None

            mujoco.mj_forward(self.model, self.data)
        except Exception as e:
            print(f"Error loading MuJoCo model: {e}")
            raise
        finally:
            os.chdir(orig_cwd)

    def get_joint_states(self):
        joint_states = []

        for i in range(self.model.njnt):
            joint_name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, i)

            angle = float(self.data.qpos[i])
            velocity = float(self.data.qvel[i])

            qfrc_applied = float(self.data.qfrc_applied[i])

            joint_state = {
                "id": i + 1,
                "name": joint_name,
                "angle": round(angle, 4),
                "velocity": round(velocity, 4),
                "torque": round(qfrc_applied, 4),
            }
            joint_states.append(joint_state)

        return joint_states

    def set_joint_target(self, joint_idx, angle):
        if 0 <= joint_idx < self.model.njnt:
            self.joint_commands[joint_idx] = angle

    def set_joint_target_by_name(self, joint_name, angle):
        joint_idx = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
        if joint_idx >= 0:
            self.joint_commands[joint_idx] = angle

    def clear_commands(self):
        self.joint_commands.clear()

    def step(self):
        for idx, angle in self.joint_commands.items():
            if idx < self.data.qpos.shape[0]:
                self.data.qpos[idx] = angle
                self.data.qvel[idx] = 0

        mujoco.mj_step(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)

        if self.viewer:
            self.viewer.sync()

    def reset(self):
        self.data.qpos[:] = 0
        self.data.qvel[:] = 0
        self.joint_commands.clear()
        mujoco.mj_forward(self.model, self.data)
