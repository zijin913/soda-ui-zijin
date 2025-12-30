#!/usr/bin/env python3
"""
Refactored URDF Logger for Rerun.
封装了 Rerun 的所有操作，外部调用者只需关注 update(joints, time)。
"""

from __future__ import annotations

import contextlib
import io
import os
import time
from pathlib import Path
from typing import Optional, Dict, Union

import numpy as np
import rerun as rr
import scipy.spatial.transform as st
import trimesh
import trimesh.visual
from urdf_parser_py import urdf as urdf_parser


# ==========================================
# 1. 辅助函数 (保持独立，无副作用)
# ==========================================


def resolve_ros_path(path: str) -> str:
    if path.startswith("package://"):
        path = path.replace("package://", "")
    return path


def origin_to_transform(origin) -> Optional[rr.Transform3D]:
    """将 URDF origin 转换为 Rerun Transform3D"""
    if origin is None:
        return None

    translation = np.array(origin.xyz) if origin.xyz else np.zeros(3)

    rotation = None
    if origin.rpy:
        # URDF 使用 rpy (roll-pitch-yaw), 对应 scipy 的 xyz
        rotation = st.Rotation.from_euler("xyz", origin.rpy).as_matrix()

    return rr.Transform3D(translation=translation, mat3x3=rotation)


def scene_to_trimeshes(scene):
    dump = scene.dump()
    if isinstance(dump, list):
        return dump
    return [dump]


# ==========================================
# 2. 核心类
# ==========================================


class URDFLogger:
    def __init__(
        self,
        filepath: str,
        entity_path_prefix: str = "",
        app_id: str = "robot_recorder",
        spawn: bool = False,  # 默认为 False，适合服务器后台运行
    ) -> None:

        # 1. 初始化 Rerun (每次实例化都会重置 Rerun 上下文)
        rr.init(app_id, spawn=spawn)

        # 2. 解析 URDF
        self.filepath = filepath
        self.root_filepath = Path(filepath).parent
        self.entity_path_prefix = entity_path_prefix

        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            if str(filepath).endswith("xacro"):
                import xacro

                xacro_doc = xacro.parse(open(filepath, encoding="utf-8"))
                xacro.process_doc(xacro_doc)
                self.urdf = urdf_parser.URDF.from_xml_string(xacro_doc.toxml())
            else:
                self.urdf = urdf_parser.URDF.from_xml_file(filepath)

        self.mat_name_to_mat = {mat.name: mat for mat in self.urdf.materials}
        self.link_map = {link.name: link for link in self.urdf.links}
        self.joint_map = {joint.name: joint for joint in self.urdf.joints}
        self.start_time = time.time()
        # 3. 记录初始静态状态
        print(f"[URDFLogger] Initialized. Logging static model from {filepath}")
        self._log_initial_state()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def update_joints(self, joint_positions: Dict[str, float]) -> None:
        """更新关节状态"""
        for joint_name, angle in joint_positions.items():
            if joint_name not in self.joint_map:
                continue

            joint = self.joint_map[joint_name]
            child_link_name = joint.child
            child_link = self.link_map[child_link_name]
            entity_path = self._get_link_entity_path(child_link)

            origin_xyz = np.array(joint.origin.xyz) if (joint.origin and joint.origin.xyz) else np.zeros(3)
            origin_rpy = np.array(joint.origin.rpy) if (joint.origin and joint.origin.rpy) else np.zeros(3)
            base_rot = st.Rotation.from_euler("xyz", origin_rpy)

            if joint.type in ["revolute", "continuous"]:
                axis = np.array(joint.axis) if joint.axis else np.array([1, 0, 0])
                rot_vec = axis * angle
                joint_rot = st.Rotation.from_rotvec(rot_vec)
                final_rot = base_rot * joint_rot
            else:
                final_rot = base_rot

            rr.log(entity_path, rr.Transform3D(translation=origin_xyz, mat3x3=final_rot.as_matrix()))

    # -------------------------------------------------------------------------
    # Internal Logic (Private)
    # -------------------------------------------------------------------------

    def _get_link_entity_path(self, link: urdf_parser.Link) -> str:
        root_name = self.urdf.get_root()
        link_names = self.urdf.get_chain(root_name, link.name)[0::2]
        path = "/".join(link_names)
        if self.entity_path_prefix:
            return f"{self.entity_path_prefix}/{path}"
        return path

    def _log_initial_state(self) -> None:
        """记录所有 Link 的视觉元素和初始 Joint 变换"""
        for link in self.urdf.links:
            entity_path = self._get_link_entity_path(link)
            self._log_link_visuals(entity_path, link)

        for joint in self.urdf.joints:
            child_link = self.link_map[joint.child]
            entity_path = self._get_link_entity_path(child_link)
            transform = origin_to_transform(joint.origin)
            if transform:
                rr.log(entity_path, transform)

    def _log_link_visuals(self, entity_path: str, link: urdf_parser.Link) -> None:
        for i, visual in enumerate(link.visuals):
            self._log_single_visual(entity_path + f"/visual_{i}", visual)

    def _log_single_visual(self, entity_path: str, visual: urdf_parser.Visual) -> None:
        material = None
        if visual.material is not None:
            if visual.material.color is None and visual.material.texture is None:
                if visual.material.name in self.mat_name_to_mat:
                    material = self.mat_name_to_mat[visual.material.name]
            else:
                material = visual.material

        transform = origin_to_transform(visual.origin)
        mesh_or_scene = None

        # --- Geometry Loading ---
        if isinstance(visual.geometry, urdf_parser.Mesh):
            raw_path = visual.geometry.filename
            resolved_path = resolve_ros_path(raw_path)
            if not os.path.isabs(resolved_path) and not os.path.exists(resolved_path):
                potential_path = self.root_filepath / resolved_path
                if potential_path.exists():
                    resolved_path = str(potential_path)
            try:
                mesh_scale = visual.geometry.scale
                # force='mesh' returns a Trimesh or Scene
                mesh_or_scene = trimesh.load(resolved_path, force="mesh")

                s = [1.0, 1.0, 1.0]
                if mesh_scale is not None:
                    s = mesh_scale if isinstance(mesh_scale, list) else [1.0, 1.0, 1.0]

                if transform is None:
                    transform = rr.Transform3D(scale=s)
                else:
                    # 如果已有 transform，这里需要叠加 scale，Trimesh 比较复杂，这里简化处理
                    # Rerun 的 Transform3D 支持 scale，但在 URDF 中 origin 只含 pos/rot
                    # visual.geometry.scale 此时通常建议直接应用到 Mesh 数据上，或者在这里构造 Transform
                    # 简单起见，这里假设 Visual 的 origin 不包含 scale，scale 来自 geometry
                    # 注意：如果 visual.origin 也有值，需要组合。这里简单处理。
                    pass
            except Exception as e:
                print(f"Error loading mesh {resolved_path}: {e}")
                return

        elif isinstance(visual.geometry, urdf_parser.Box):
            mesh_or_scene = trimesh.creation.box(extents=visual.geometry.size).to_mesh()

        elif isinstance(visual.geometry, urdf_parser.Cylinder):
            mesh_or_scene = trimesh.creation.cylinder(
                radius=visual.geometry.radius, height=visual.geometry.length, sections=32
            ).to_mesh()

        elif isinstance(visual.geometry, urdf_parser.Sphere):
            mesh_or_scene = trimesh.creation.icosphere(
                radius=visual.geometry.radius,
            ).to_mesh()

        if mesh_or_scene is None:
            return

        # --- Logging ---
        if isinstance(mesh_or_scene, trimesh.Scene):
            for i, m in enumerate(scene_to_trimeshes(mesh_or_scene)):
                self._log_trimesh_internal(entity_path + f"/{i}", m, transform)
        else:
            # 应用材质颜色
            if material and material.color:
                mesh_or_scene.visual = trimesh.visual.ColorVisuals(
                    mesh=mesh_or_scene, vertex_colors=material.color.rgba
                )
            self._log_trimesh_internal(entity_path, mesh_or_scene, transform)

    def _log_trimesh_internal(self, entity_path: str, mesh: trimesh.Trimesh, transform: rr.Transform3D):
        """
        内部方法：处理 Numpy 内存布局并 log 到 Rerun。
        """
        # 1. 确保是标准的 Numpy 数组且内存连续 (关键修复)
        positions = np.ascontiguousarray(mesh.vertices, dtype=np.float32)
        indices = np.ascontiguousarray(mesh.faces, dtype=np.uint32)

        # 2. 处理法线
        normals = None
        if hasattr(mesh, "vertex_normals") and mesh.vertex_normals is not None:
            n = np.ascontiguousarray(mesh.vertex_normals, dtype=np.float32)
            if n.shape[0] == positions.shape[0] and n.shape[1] == 3:
                normals = n

        # 3. 处理颜色
        albedo_factor = None
        vertex_colors = None

        if hasattr(mesh.visual, "vertex_colors") and len(mesh.visual.vertex_colors) > 0:
            vertex_colors = np.ascontiguousarray(mesh.visual.vertex_colors, dtype=np.uint8)

        # 4. 记录 Geometry
        rr.log(
            entity_path,
            rr.Mesh3D(
                vertex_positions=positions,
                triangle_indices=indices,
                vertex_normals=normals,
                vertex_colors=vertex_colors,
                albedo_factor=albedo_factor,
            ),
        )

        # 5. 记录 Transform (Static visual transform)
        if transform:
            rr.log(entity_path, transform)

    def set_time(self, timestamp: float):
        """设置当前时间轴"""
        rr.set_time("sim_time", duration=timestamp - self.start_time)

    def log_image(self, entity_path: str, image: np.ndarray):
        """记录图像 (BGR or RGB)"""
        # Rerun 默认期望 RGB，OpenCV 是 BGR，通常需要转换，或者直接传
        # 这里假设传入的是 OpenCV 读取的 (BGR)，Rerun 的 rr.Image 可以自动处理，或者手动指定
        rr.log(entity_path, rr.Image(image))

    def log_points(self, entity_path: str, positions: np.ndarray, colors: Optional[Any] = None):
        """
        记录点云
        自动处理 (N, 6) 格式的数据 (通常是 XYZRGB)
        """
        # 确保数据是 numpy 数组
        if not isinstance(positions, np.ndarray):
            positions = np.array(positions)

        # 修复 (N, 6) 形状错误
        # 如果数据包含 6 列，通常前 3 列是 XYZ，后 3 列是 RGB
        valid_positions = positions
        valid_colors = colors

        if positions.ndim == 2 and positions.shape[1] == 6:
            # 切片：取前3列作为位置
            valid_positions = positions[:, :3]

            # 如果外部没有指定颜色，且数据里包含颜色信息（后3列），则使用数据里的颜色
            if valid_colors is None:
                # 假设后3列是颜色，且范围可能是 0-1 或 0-255，Rerun 通常能自动处理
                valid_colors = positions[:, 3:]

        # 记录
        rr.log(entity_path, rr.Points3D(valid_positions, colors=valid_colors))

    def log_scalar(self, entity_path: str, value: float):
        """记录标量值"""
        # 修复 AttributeError: 'rerun' has no attribute 'Scalar'
        # 新版 API 使用 rr.Scalars (复数)
        rr.log(entity_path, rr.Scalars(value))

    def save(self, path: str) -> None:
        """
        将录制的数据保存到文件 (.rrd)。

        用法提示：
        1. 如果在 update 循环结束后调用，会将内存中所有历史数据 Dump 到文件。
        2. 如果在 __init__ 后立即调用，后续的 log 数据会流式写入该文件 (Stream模式)。

        Args:
            path: 文件保存路径 (例如 "recordings/output.rrd")
        """
        try:
            # 确保目录存在
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)

            rr.save(path)
            print(f"[Rerun] Recording saved successfully to: {path}")
        except Exception as e:
            print(f"[Rerun] Failed to save recording: {e}")


# ==========================================
# 3. 主程序 (External Caller)
# ==========================================
def main():
    urdf_file = "assets/xpkg_urdf_archer_l6y/xpkg_urdf_archer_l6y.urdf"

    # 实例化 Logger (自动 Init Rerun, 自动 Spawn, 自动加载并显示静态模型)
    logger = URDFLogger(urdf_file, spawn=True)

    print("Animation starting...")
    angle_deg = 0.0
    start_ts = time.time()

    try:
        while True:
            # 计算当前状态
            current_time = time.time()
            angle_rad = np.deg2rad(angle_deg)

            # 准备关节数据
            joint_angles = {}
            # 简单示例：让所有旋转关节动起来
            for joint in logger.urdf.joints:
                if joint.type in ["revolute", "continuous"]:
                    joint_angles[joint.name] = angle_rad

            # 更新 Rerun (Logger 内部处理 set_time_seconds 和 log)
            logger.update(joint_angles, time_seconds=current_time)

            # 模拟循环
            time.sleep(0.02)  # 50Hz
            angle_deg += 1.0
            if angle_deg > 360:
                angle_deg -= 360

    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
