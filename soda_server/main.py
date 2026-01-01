import asyncio
import json
import cv2
import time
from aiohttp import web, WSMsgType
import struct
import os
import numpy as np
from datetime import datetime
import msgpack

from mujoco_manager import MujocoManager
from robot_interface import SimRobot

# 唯一需要的日志依赖
from urdf_logger import URDFLogger

# 配置
HOST = "0.0.0.0"
PORT = 8080
VIDEO_PATH = "test_30fps.mp4"
TARGET_FPS = 30
URDF_PATH = "public/l6y_gp100/l6y_gp100.urdf"
MJCF_PATH = "public/l6y_gp100/l6y_gp100.xml"
STATIC_PATH = "public"
POINTCLOUD_PATH = "Wheat_Alsen_F6_2023-06-30-1836_fused_output_cluster_2.npy"
RECORDING_DIR = "recordings"

# 全局变量
robot = None

# 录制相关状态
recording_enabled = False
urdf_logger = None  # 这是一个 URDFLogger 实例
current_file_path = None


def init_mujoco():
    global robot
    print("Initializing MuJoCo...")
    if robot is None:
        try:
            enable_gui = os.environ.get("MUJOCO_GUI", "true").lower() == "true"
            robot = SimRobot(
                MJCF_PATH,
                enable_gui=enable_gui,
                video_path=VIDEO_PATH,
                pointcloud_path=POINTCLOUD_PATH,
            )
            print("MuJoCo initialized successfully")
        except Exception as e:
            print(f"Failed to initialize MuJoCo: {e}")
            raise


def state_to_joint_states(state, joint_names):
    """
    将 RobotInterface.get_state() 返回的 numpy 格式转换为原来的 list[dict] 格式
    """
    joint_states = []
    for i in range(len(state["q"])):
        joint_states.append(
            {
                "id": i,
                "name": joint_names[i] if i < len(joint_names) else f"joint_{i}",
                "angle": float(state["q"][i]),
                "velocity": float(state["dq"][i]),
                "torque": float(state["tau"][i]),
            }
        )
    return joint_states


async def record_handler(request):
    """
    处理录制请求。
    逻辑：
    - Start: 创建新的 URDFLogger 实例 (这会初始化新的 Rerun Session)，并绑定文件。
    - Stop: 只是停止数据写入的标志位，因为是流式写入，不需要显式关闭文件。
    """
    global recording_enabled, urdf_logger, current_file_path

    try:
        data = await request.json()
        action = data.get("action")

        if action == "start":
            # 1. 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"rec_{timestamp}.rrd"
            current_file_path = os.path.join(RECORDING_DIR, filename)

            # 2. 实例化 Logger
            # 注意：每次 Start 都重新实例化，这样会调用 rr.init() 生成新的 Recording ID
            # spawn=False 表示不弹窗，只后台录制
            print("Initializing URDFLogger for recording...")
            urdf_logger = URDFLogger(URDF_PATH, entity_path_prefix="robot")

            # 3. 开启流式保存
            urdf_logger.save(current_file_path)

            recording_enabled = True
            print(f"Recording started. Stream linked to: {current_file_path}")

            return web.json_response(
                {"status": "recording_started", "file": current_file_path}
            )

        elif action == "stop":
            if not recording_enabled:
                return web.json_response({"error": "Not recording"}, status=400)

            recording_enabled = False
            # 流式写入模式下，停止调用 log 方法即停止录制
            # 也可以选择在这里 urdf_logger = None 来释放资源，但为了保持最后状态可视，可以保留
            print(f"Recording stopped. Data saved to: {current_file_path}")

            return web.json_response(
                {"status": "recording_stopped", "saved_to": current_file_path}
            )

        else:
            return web.json_response({"error": "Invalid action"}, status=400)
    except Exception as e:
        print(f"Record error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_joint_command(ws, data):
    """处理关节控制命令"""
    global robot

    joint_name = data.get("joint_name")
    delta_angle = data.get("delta_angle", 0)
    joint_idx = (
        robot.joint_names.index(joint_name) if joint_name in robot.joint_names else -1
    )
    if joint_idx >= 0:
        current_state = robot.get_state()
        q = current_state["q"].copy()
        q[joint_idx] += delta_angle
        robot.set_command(q)


async def handle_gripper_set(ws, data):
    """处理夹爪距离设置命令"""
    global robot

    distance = data.get("distance", 0.05)
    if distance < 0.01:
        distance = 0.01
    elif distance > 0.1:
        distance = 0.1

    print("data", data)
    print("now=", robot.get_gripper_distance())
    robot.set_gripper_distance(distance)


async def message_handler(ws):
    """处理前端消息的协程"""
    try:
        while not ws.closed:
            msg = await ws.receive()
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "joint_command":
                        await handle_joint_command(ws, data)
                    elif msg_type == "gripper_set":
                        await handle_gripper_set(ws, data)
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        print(f"Message handler error: {e}")


async def broadcast_handler(ws):
    """定时发送数据的协程"""
    global robot, urdf_logger

    try:
        while not ws.closed:
            start_time = time.time()
            current_ts = time.time()

            # 1. 读取视频帧
            frame = robot.get_rgb()

            # 2. 物理引擎步进 & 获取状态
            robot.step()
            state = robot.get_state()
            joint_states = state_to_joint_states(state, robot.joint_names)

            # 3. 记录数据
            if recording_enabled and urdf_logger is not None:
                urdf_logger.set_time(current_ts)

                if frame is not None:
                    urdf_logger.log_image("camera/rgb", frame)

                pointcloud_data = robot.get_point_cloud()
                if pointcloud_data is not None and len(pointcloud_data) > 0:
                    urdf_logger.log_points(
                        "pointcloud", pointcloud_data, colors=[0, 255, 0]
                    )

                joint_map = {j["name"]: j["angle"] for j in joint_states}
                urdf_logger.update_joints(joint_map)

                for joint in joint_states:
                    base_path = f"joints/{joint['name']}"
                    urdf_logger.log_scalar(f"{base_path}/angle", joint["angle"])
                    urdf_logger.log_scalar(f"{base_path}/velocity", joint["velocity"])
                    urdf_logger.log_scalar(f"{base_path}/torque", joint["torque"])

            # 4. 使用 MessagePack 统一发送数据
            video_bytes = None
            if frame is not None:
                _, buffer = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70]
                )
                video_bytes = buffer.tobytes()

            pointcloud_data = robot.get_point_cloud()
            pc_data = None
            if pointcloud_data is not None:
                pc_data = pointcloud_data.tolist()

            gripper_distance = robot.get_gripper_distance()

            packed_data = {
                "timestamp": current_ts,
                "video": video_bytes,
                "pointcloud": pc_data,
                "joints": joint_states,
                "gripper_distance": gripper_distance,
            }

            packed_bytes = msgpack.packb(packed_data, use_bin_type=True)
            header = struct.pack("I", len(packed_bytes))
            await ws.send_bytes(header + packed_bytes)

            # 帧率控制
            process_time = time.time() - start_time
            sleep_time = max(0, (1.0 / TARGET_FPS) - process_time)
            await asyncio.sleep(sleep_time)
    except Exception as e:
        print(f"Broadcast handler error: {e}")


async def websocket_handler(request):
    global robot, urdf_logger

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    print("Client connected")

    if robot is None:
        init_mujoco()

    try:
        await asyncio.gather(
            message_handler(ws),
            broadcast_handler(ws),
        )
    except Exception as e:
        print(f"Connection error: {e}")
    finally:
        print("Client disconnected")
        return ws


# ... (joint_command_handler, get_urdf_handler, cors_middleware 保持不变) ...


async def joint_command_handler(request):
    global robot
    if robot is None:
        return web.json_response({"error": "Robot not initialized"}, status=503)
    return web.json_response({"error": "Use WebSocket for joint control"}, status=400)


async def get_urdf_handler(request):
    return web.json_response(
        {"url": f"http://localhost:{PORT}/assets/l6y_gp100/l6y_gp100.urdf"}
    )


async def gripper_handler(request):
    global robot
    if robot is None:
        return web.json_response({"error": "Robot not initialized"}, status=503)
    try:
        data = await request.json()
        distance = data.get("distance", 0.05)
        if distance < 0.01:
            distance = 0.01
        elif distance > 0.1:
            distance = 0.1
        robot.set_gripper_distance(distance)
        return web.json_response({"status": "success", "distance": distance})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def gripper_distance_handler(request):
    global robot
    if robot is None:
        return web.json_response({"error": "Robot not initialized"}, status=503)
    try:
        distance = robot.get_gripper_distance()
        return web.json_response({"distance": distance})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def get_gripper_joints_handler(request):
    """获取 gripper 相关的关节列表"""
    global robot
    if robot is None:
        return web.json_response({"error": "Robot not initialized"}, status=503)
    try:
        gripper_joints = []
        for joint_name in robot.joint_names:
            if joint_name.startswith("gripper"):
                gripper_joints.append(joint_name)
        return web.json_response({"joints": gripper_joints})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def get_recordings_handler(request):
    """获取 recordings 文件夹中的所有录制文件"""
    try:
        if not os.path.exists(RECORDING_DIR):
            return web.json_response({"files": []})

        files = []
        for filename in os.listdir(RECORDING_DIR):
            if os.path.isfile(os.path.join(RECORDING_DIR, filename)):
                files.append(filename)

        return web.json_response({"files": files})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        response = web.Response()
        response.headers.update(
            {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            }
        )
        return response
    response = await handler(request)
    response.headers.update(
        {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )
    return response


app = web.Application(middlewares=[cors_middleware])
app.add_routes(
    [
        web.get("/ws", websocket_handler),
        web.get("/urdf", get_urdf_handler),
        web.post("/api/gripper/set", gripper_handler),
        web.get("/api/gripper/distance", gripper_distance_handler),
        web.get("/api/joints/gripper", get_gripper_joints_handler),
        web.post("/api/record", record_handler),
        web.get("/api/recordings", get_recordings_handler),
        web.static("/assets", os.path.abspath(STATIC_PATH)),
    ]
)

if __name__ == "__main__":
    os.makedirs(RECORDING_DIR, exist_ok=True)
    init_mujoco()
    print(f"Server started at http://{HOST}:{PORT}")
    web.run_app(app, host=HOST, port=PORT)
