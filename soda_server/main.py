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
from replay_manager import ReplayManager

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
current_mode = "realtime"  # "realtime" or "replay"
replay_manager = None  # ReplayManager 实例

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
    - Start: 创建新的 URDFLogger 实例 (这会初始化新的 DuckDB 连接)，并绑定文件。
    - Stop: 显式关闭 Logger 以断开 DB 连接。
    """
    global recording_enabled, urdf_logger, current_file_path

    try:
        data = await request.json()
        action = data.get("action")

        if action == "start":
            # 1. 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Base name for parquet files
            filename = f"rec_{timestamp}"
            current_file_path = os.path.join(RECORDING_DIR, filename)

            # 2. 实例化 Logger
            # 自动创建并流式写入 LeRobot 格式
            print(f"Initializing URDFLogger for recording: {current_file_path}")

            # Determine num_points and img_shape from robot if available
            num_points = 1024
            img_shape = (480, 640)
            if robot:
                pc = robot.get_point_cloud()
                if pc is not None:
                    num_points = len(pc)

                rgb = robot.get_rgb()
                if rgb is not None:
                    img_shape = rgb.shape[:2]  # (H, W)

            urdf_logger = URDFLogger(
                URDF_PATH,
                entity_path_prefix="robot",
                db_path=current_file_path,
                num_points=num_points,
                img_shape=img_shape,
            )

            recording_enabled = True
            print(f"Recording started. Stream linked to: {current_file_path}")

            return web.json_response(
                {"status": "recording_started", "file": current_file_path}
            )

        elif action == "stop":
            if not recording_enabled:
                return web.json_response({"error": "Not recording"}, status=400)

            recording_enabled = False
            if urdf_logger:
                urdf_logger.close()
                urdf_logger = None

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
        # Get limits from MuJoCo model
        model = robot.sim_manager.model
        min_angle, max_angle = model.jnt_range[joint_idx]

        current_state = robot.get_state()
        q = current_state["q"].copy()

        # Calculate potential new angle
        new_angle = q[joint_idx] + delta_angle

        # Clamp to limits
        if new_angle < min_angle:
            new_angle = min_angle
        elif new_angle > max_angle:
            new_angle = max_angle

        q[joint_idx] = new_angle
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

                    if current_mode == "realtime":
                        if msg_type == "joint_command":
                            await handle_joint_command(ws, data)
                        elif msg_type == "gripper_set":
                            await handle_gripper_set(ws, data)
                    else:
                        # In replay mode, ignore control commands
                        pass
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        print(f"Message handler error: {e}")


async def broadcast_handler(ws):
    """定时发送数据的协程"""
    global robot, urdf_logger, replay_manager, current_mode

    try:
        while not ws.closed:
            start_time = time.time()
            current_ts = time.time()

            if current_mode == "realtime":
                # Realtime mode: Get data from robot
                frame = robot.get_rgb()

                robot.step()
                state = robot.get_state()
                joint_states = state_to_joint_states(state, robot.joint_names)

                # 记录数据
                if recording_enabled and urdf_logger is not None:
                    if frame is not None:
                        await urdf_logger.log_image_async(
                            "camera/rgb", frame, time_seconds=current_ts
                        )

                    pointcloud_data = robot.get_point_cloud()
                    if pointcloud_data is not None and len(pointcloud_data) > 0:
                        colors = np.array(
                            [[0, 255, 0]] * len(pointcloud_data), dtype=np.uint8
                        )
                        await urdf_logger.log_points_async(
                            "pointcloud",
                            pointcloud_data,
                            colors=colors,
                            time_seconds=current_ts,
                        )

                    joint_map = {j["name"]: j["angle"] for j in joint_states}
                    await urdf_logger.update_joints_async(
                        joint_map, time_seconds=current_ts
                    )

                    for joint in joint_states:
                        base_path = f"joints/{joint['name']}"
                        await urdf_logger.log_scalar_async(
                            f"{base_path}/angle",
                            joint["angle"],
                            time_seconds=current_ts,
                        )
                        await urdf_logger.log_scalar_async(
                            f"{base_path}/velocity",
                            joint["velocity"],
                            time_seconds=current_ts,
                        )
                        await urdf_logger.log_scalar_async(
                            f"{base_path}/torque",
                            joint["torque"],
                            time_seconds=current_ts,
                        )

                    await urdf_logger.commit_frame()

                # Prepare data for sending
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
                    "mode": "realtime",
                }

            else:
                # Replay mode: Frontend handles playback with full data
                await asyncio.sleep(1.0)
                continue

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
    """获取 recordings 文件夹中的所有录制文件 (Based on LeRobot format directories)"""
    try:
        if not os.path.exists(RECORDING_DIR):
            return web.json_response({"files": []})

        files = []
        for filename in os.listdir(RECORDING_DIR):
            dir_path = os.path.join(RECORDING_DIR, filename)
            if os.path.isdir(dir_path):
                # Check if it's a LeRobot dataset (has meta/info.json)
                if os.path.exists(os.path.join(dir_path, "meta", "info.json")):
                    files.append(filename)

        return web.json_response({"files": files})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def set_mode_handler(request):
    """设置运行模式（realtime 或 replay）"""
    global current_mode, replay_manager

    try:
        data = await request.json()
        new_mode = data.get("mode")

        if new_mode not in ["realtime", "replay"]:
            return web.json_response(
                {"error": "Invalid mode. Use 'realtime' or 'replay'"}, status=400
            )

        current_mode = new_mode

        # Reset replay manager when switching modes
        if new_mode == "realtime":
            replay_manager = None

        return web.json_response({"status": "success", "mode": current_mode})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def load_replay_handler(request):
    """加载回放文件"""
    global replay_manager

    try:
        data = await request.json()
        filename = data.get("filename")

        if not filename:
            return web.json_response({"error": "Filename is required"}, status=400)

        filepath = os.path.join(RECORDING_DIR, filename)

        if not os.path.exists(filepath):
            return web.json_response(
                {"error": "Recording directory not found"}, status=404
            )

        replay_manager = ReplayManager(filepath)

        return web.json_response(
            {
                "status": "success",
                "total_frames": replay_manager.total_frames,
                "duration": replay_manager.get_duration(),
            }
        )
    except Exception as e:
        print(f"Failed to load replay: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def get_replay_status_handler(request):
    """获取当前回放状态"""
    global replay_manager

    try:
        if replay_manager is None:
            return web.json_response({"is_loaded": False})

        return web.json_response(
            {
                "is_loaded": True,
                "total_frames": replay_manager.total_frames,
                "current_frame": replay_manager.current_frame_idx,
                "progress": replay_manager.get_progress(),
                "current_timestamp": replay_manager.get_current_timestamp(),
                "duration": replay_manager.get_duration(),
                "is_playing": replay_manager.is_playing,
            }
        )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def get_replay_trajectory_handler(request):
    """获取完整的轨迹数据（不含视频/点云）"""
    global replay_manager

    try:
        if replay_manager is None:
            return web.json_response({"error": "No replay loaded"}, status=400)

        trajectory_resp = replay_manager.get_trajectory()
        return web.json_response(trajectory_resp.to_dict())
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def get_replay_chunk_handler(request):
    """获取视频/点云数据块 (MessagePack)"""
    global replay_manager
    try:
        if replay_manager is None:
            return web.json_response({"error": "No replay loaded"}, status=400)

        # Get query params
        try:
            start_idx = int(request.query.get("start_idx", 0))
            length = int(request.query.get("length", 300))  # Default 10s @ 30fps
        except ValueError:
            return web.json_response({"error": "Invalid params"}, status=400)

        chunk_data = replay_manager.get_chunk(start_idx, length)

        # Pack with MessagePack
        packed_bytes = msgpack.packb(chunk_data, use_bin_type=True)

        return web.Response(body=packed_bytes, content_type="application/x-msgpack")
    except Exception as e:
        print(f"Chunk error: {e}")
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
        web.post("/api/mode/set", set_mode_handler),
        web.post("/api/replay/load", load_replay_handler),
        web.get("/api/replay/status", get_replay_status_handler),
        web.get("/api/replay/trajectory", get_replay_trajectory_handler),
        web.get("/api/replay/chunk", get_replay_chunk_handler),
        web.static("/assets", os.path.abspath(STATIC_PATH)),
    ]
)

if __name__ == "__main__":
    os.makedirs(RECORDING_DIR, exist_ok=True)
    init_mujoco()
    print(f"Server started at http://{HOST}:{PORT}")
    web.run_app(app, host=HOST, port=PORT)
