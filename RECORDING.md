# Recording with Rerun

This system uses Rerun to record robot state during operation.

## Installation

Install dependencies using uv:

```bash
cd soda_server
uv sync
```

## Usage

1. Start the server:
```bash
cd soda_server
uv run main.py
```

2. In the web UI, click the **Record button** (red dot) in the top bar to start/stop recording.

3. The Rerun viewer will automatically launch when recording starts.

4. Recordings are saved to `soda_server/recordings/` as `.rrd` files.

## Recorded Data

The system records the following data when recording is enabled:

- **URDF Robot Model**: Complete robot mesh structure at `/robot/*` with initial state
- **Joint Transforms**: Real-time joint transformations for robot pose at `/robot/*`
- **Point Cloud**: 3D point cloud data at `/pointcloud`
- **RGB Camera**: Video frames at `/camera/rgb`
- **Joint Angles**: Per-joint angle values at `/joints/{joint_name}/angle`
- **Joint Velocities**: Per-joint velocity values at `/joints/{joint_name}/velocity`
- **Joint Torques**: Per-joint torque values at `/joints/{joint_name}/torque`

All data is timestamped with `stable_time`.

## URDF Recording

When recording starts:
1. URDF model is loaded from `public/xpkg_urdf_archer_l6y/xpkg_urdf_archer_l6y.urdf`
2. Initial mesh geometry and transforms are logged to Rerun
3. Each frame updates joint transforms based on MuJoCo physics state

## API Endpoint

`POST /api/record`

Request body:
```json
{
  "action": "start" | "stop"
}
```

Response (start):
```json
{
  "status": "recording_started",
  "file": "recordings/rec_20241229_123456.rrd",
  "recording_id": "uuid-here"
}
```

Response (stop):
```json
{
  "status": "recording_stopped",
  "saved_to": "recordings/rec_20241229_123456.rrd"
}
```

## Usage

1. Start the server:
```bash
cd soda_server
uv run main.py
```

2. In the web UI, click the **Record button** (red dot) in the top bar to start/stop recording.

3. The Rerun viewer will automatically launch when recording starts.

## Recorded Data

The system records the following data when recording is enabled:

- **Point Cloud**: 3D point cloud data at `/pointcloud`
- **RGB Camera**: Video frames at `/camera/rgb`
- **Joint Angles**: Per-joint angle values at `/joints/{joint_name}/angle`
- **Joint Velocities**: Per-joint velocity values at `/joints/{joint_name}/velocity`
- **Joint Torques**: Per-joint torque values at `/joints/{joint_name}/torque`

All data is timestamped with `stable_time`.

## API Endpoint

`POST /api/record`

Request body:
```json
{
  "action": "start" | "stop"
}
```

Response:
```json
{
  "status": "recording_started" | "recording_stopped"
}
```
