# Recording & Replay Test Script

## Overview

`test_recording.py` is a test script for testing SODA's recording and replay functionality.

## Features

1. **Recording Test**
   - Connect to the WebSocket server
   - Start recording
   - Collect 10 seconds of data (about 290 frames)
   - Save RGB frames as an MP4 video file

2. **Replay API Test**
   - Retrieve the list of recording files
   - Switch to replay mode
   - Check replay status
   - Reset to realtime mode

## Usage

### 1. Start the Server

```bash
cd soda_server
uv run python main.py
```

Or run it in the background:
```bash
cd soda_server
nohup uv run python main.py > server.log 2>&1 &
```

### 2. Run the Test Script

```bash
cd soda_server
uv run python test_recording.py
```

### 3. View Results

After the test completes, the following files are generated:

- **Recording file**: `recordings/rec_YYYYMMDD_HHMMSS.rrd`
  - Complete recording file in RRD format
  - Contains video, point cloud, and joint data

- **Video file**: `test_recordings/test_recording_YYYYMMDD_HHMMSS.mp4`
  - RGB video in MP4 format
  - Can be opened with any video player

## Example Output

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

## Test Results

A successful test should:

1. ✅ Server responds normally
2. ✅ WebSocket connection succeeds
3. ✅ Recording starts successfully
4. ✅ Captures about 290 frames (10 seconds @ 30 FPS)
5. ✅ Recording stops successfully
6. ✅ Video saved successfully (about 6MB)
7. ✅ RRD file created successfully (about 100MB)
8. ✅ API test passes

## File Size Reference

- **RRD file**: ~100MB / 10 seconds
  - Contains complete data (video, point cloud, joints)
  - Rerun compressed format

- **MP4 video**: ~6MB / 10 seconds
  - RGB video frames only
  - H.264 encoded, 70% quality

## Troubleshooting

### Issue: Server Not Running

```
Server is not running or not accessible
```

**Solution**: Start the server
```bash
cd soda_server
uv run python main.py
```

### Issue: Port Already in Use

```
OSError: [Errno 98] address already in use
```

**Solution**:
1. Find the process occupying the port: `lsof -i :8080`
2. Kill the process: `kill <PID>`
3. Restart the server

### Issue: Cannot Connect to WebSocket

```
Failed to connect to host localhost:8080
```

**Solution**:
1. Check whether the server is running
2. Check firewall settings
3. Confirm the URL is correct

## Custom Testing

To change the recording duration, edit `test_recording.py`:

```python
record_duration = 10  # Change to the number of seconds you need
```

## Next Steps

After the test completes, you can test the replay functionality through the frontend interface:

1. Open the frontend: `cd soda_ui && npm run dev`
2. Switch to replay mode (RP button)
3. Select the recorded RRD file
4. Use the playback control buttons to replay

## Technical Details

- **WebSocket**: Uses the `websockets` library for asynchronous connection
- **MessagePack**: Uses `msgpack` to decode binary data
- **Video Encoding**: Uses OpenCV `VideoWriter` with MP4V encoding
- **API Testing**: Uses `aiohttp` to test REST API endpoints
