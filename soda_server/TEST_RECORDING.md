# Recording & Replay Test Script

## 概述

`test_recording.py` 是一个用于测试 SODA 录制和回放功能的测试脚本。

## 功能

1. **录制测试**
   - 连接到 WebSocket 服务器
   - 启动录制
   - 收集 10 秒钟的数据（约 290 帧）
   - 保存 RGB 帧为 MP4 视频文件

2. **回放 API 测试**
   - 获取录制文件列表
   - 切换到回放模式
   - 检查回放状态
   - 重置为实时模式

## 使用方法

### 1. 启动服务器

```bash
cd soda_server
uv run python main.py
```

或者在后台运行：
```bash
cd soda_server
nohup uv run python main.py > server.log 2>&1 &
```

### 2. 运行测试脚本

```bash
cd soda_server
uv run python test_recording.py
```

### 3. 查看结果

测试完成后，会生成以下文件：

- **录制文件**: `recordings/rec_YYYYMMDD_HHMMSS.rrd`
  - RRD 格式的完整录制文件
  - 包含视频、点云、关节数据

- **视频文件**: `test_recordings/test_recording_YYYYMMDD_HHMMSS.mp4`
  - MP4 格式的 RGB 视频
  - 可使用任何视频播放器打开

## 输出示例

```
============================================================
SODA Recording & Replay Test Script
============================================================

Checking if server is running...
Server is running!
Connecting to ws://localhost:8080/ws...
Connected to server!

=== Starting Recording ===
Recording started...
Captured 30 frames (28.7 fps)
Captured 60 frames (28.9 fps)
...
Captured 270 frames (29.0 fps)
Recording duration (10s) reached

=== Stopping Recording ===
Recording stopped

Saving video to: test_recordings/test_recording_20260101_223346.mp4
Frame size: (640, 360), FPS: 30
Writing frame 100/290
Writing frame 200/290
Video saved successfully!

=== Test Complete ===
Total RGB frames captured: 290
Recording duration: 10.30s

============================================================
Testing Replay API ===

1. Getting recordings list...
   Recordings: ['rec_20260101_220533.rrd']

2. Setting mode to replay...
   Mode set: replay

3. Getting replay status...
   Status: {'is_loaded': False}

4. Resetting mode to realtime...
   Mode reset: realtime
============================================================
```

## 测试结果

成功的测试应该：

1. ✅ 服务器响应正常
2. ✅ WebSocket 连接成功
3. ✅ 录制启动成功
4. ✅ 捕获约 290 帧（10 秒 @ 30 FPS）
5. ✅ 录制停止成功
6. ✅ 视频保存成功（约 6MB）
7. ✅ RRD 文件创建成功（约 100MB）
8. ✅ API 测试通过

## 文件大小参考

- **RRD 文件**: ~100MB / 10 秒
  - 包含完整数据（视频、点云、关节）
  - Rerun 压缩格式

- **MP4 视频**: ~6MB / 10 秒
  - 仅 RGB 视频帧
  - H.264 编码，70% 质量

## 故障排除

### 问题：服务器未运行

```
Server is not running or not accessible
```

**解决方法**：启动服务器
```bash
cd soda_server
uv run python main.py
```

### 问题：端口被占用

```
OSError: [Errno 98] address already in use
```

**解决方法**：
1. 查找占用端口的进程：`lsof -i :8080`
2. 杀死进程：`kill <PID>`
3. 重新启动服务器

### 问题：无法连接 WebSocket

```
Failed to connect to host localhost:8080
```

**解决方法**：
1. 检查服务器是否在运行
2. 检查防火墙设置
3. 确认 URL 正确

## 自定义测试

修改录制时长，编辑 `test_recording.py`:

```python
record_duration = 10  # 修改为你需要的秒数
```

## 下一步

测试完成后，可以通过前端界面测试回放功能：

1. 打开前端：`cd soda_ui && npm run dev`
2. 切换到回放模式（RP 按钮）
3. 选择录制的 RRD 文件
4. 使用播放控制按钮回放

## 技术细节

- **WebSocket**: 使用 `websockets` 库异步连接
- **MessagePack**: 使用 `msgpack` 解码二进制数据
- **视频编码**: 使用 OpenCV `VideoWriter`，MP4V 编码
- **API 测试**: 使用 `aiohttp` 测试 REST API 端点
