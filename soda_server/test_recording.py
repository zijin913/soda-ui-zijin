#!/usr/bin/env python3
"""
Test script for recording and replay functionality.
Starts by server, records data, and saves all data types.
"""

import asyncio
import websockets
import aiohttp
import json
import struct
import msgpack
import cv2
import numpy as np
import time
import os
from datetime import datetime
import signal
import sys


class TestRecorder:
    def __init__(self):
        self.rgb_frames = []
        self.pointclouds = []
        self.joints_data = []
        self.gripper_distances = []
        self.timestamps = []
        self.recording_started = False
        self.total_frames = 0
        self.start_time = None

    async def connect_to_server(self):
        uri = "ws://localhost:8080/ws"
        print(f"Connecting to {uri}...")

        try:
            async with websockets.connect(uri) as websocket:
                print("Connected to server!")
                await self.start_recording(websocket)

        except Exception as e:
            print(f"Failed to connect: {e}")
            sys.exit(1)

    async def start_recording(self, websocket):
        print("\n=== Starting Recording ===")

        await websocket.send(json.dumps({"type": "record", "action": "start"}))
        print("Recording started...")

        record_duration = 10
        self.start_time = time.time()

        try:
            while True:
                elapsed = time.time() - self.start_time
                if elapsed >= record_duration:
                    print(f"\nRecording duration ({record_duration}s) reached")
                    break

                data = await websocket.recv()
                if isinstance(data, bytes):
                    self.handle_binary_data(data)

                await asyncio.sleep(0.01)

        except KeyboardInterrupt:
            print("\nRecording interrupted by user")

        await self.stop_recording(websocket)

    async def stop_recording(self, websocket):
        print("\n=== Stopping Recording ===")

        await websocket.send(json.dumps({"type": "record", "action": "stop"}))
        print("Recording stopped")

        self.save_video()
        self.save_pointclouds()
        self.save_joints()
        self.save_gripper_distances()
        self.save_summary()

        print(f"\n=== Test Complete ===")
        print(f"Total frames captured: {self.total_frames}")
        duration = (time.time() - self.start_time) if self.start_time else 0
        print(f"Recording duration: {duration:.2f}s")

    def handle_binary_data(self, data):
        try:
            if len(data) < 4:
                return

            header_size = struct.unpack("I", data[:4])[0]
            packed_data = data[4 : 4 + header_size]

            decoded = msgpack.unpackb(packed_data, raw=False)

            timestamp = decoded.get("timestamp", 0)
            self.timestamps.append(timestamp)

            if decoded.get("video"):
                video_bytes = decoded["video"]
                nparr = np.frombuffer(video_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                if frame is not None:
                    self.rgb_frames.append(frame)
                    self.total_frames += 1

                    if self.total_frames % 30 == 0:
                        elapsed = time.time() - (
                            self.start_time if self.start_time else time.time()
                        )
                        fps = self.total_frames / elapsed if elapsed > 0 else 0
                        print(
                            f"Captured {self.total_frames} frames ({fps:.1f} fps)",
                            end="\r",
                        )

            if decoded.get("pointcloud"):
                pointcloud = decoded["pointcloud"]
                if isinstance(pointcloud, list) and len(pointcloud) > 0:
                    self.pointclouds.append(np.array(pointcloud))

            if decoded.get("joints"):
                joints = decoded["joints"]
                self.joints_data.append({"timestamp": timestamp, "joints": joints})

            if decoded.get("gripper_distance") is not None:
                gripper_dist = decoded["gripper_distance"]
                self.gripper_distances.append(
                    {"timestamp": timestamp, "distance": gripper_dist}
                )

        except Exception as e:
            print(f"\nError handling data: {e}")

    def save_video(self):
        if not self.rgb_frames:
            print("No frames to save!")
            return

        output_dir = "test_recordings"
        os.makedirs(output_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        codecs = [
            ("XVID", ".avi"),
            ("MJPG", ".avi"),
            ("mp4v", ".avi"),
        ]

        video_path = None
        video_writer = None

        for fourcc_str, ext in codecs:
            try:
                test_path = os.path.join(output_dir, f"test_recording_{ts}{ext}")
                frame_size = (self.rgb_frames[0].shape[1], self.rgb_frames[0].shape[0])
                fps = 30

                print(f"\nTrying codec: {fourcc_str}")

                fourcc = -1
                video_writer = cv2.VideoWriter(test_path, fourcc, fps, frame_size)

                video_writer.write(self.rgb_frames[0])

                if video_writer.isOpened():
                    print(f"Codec {fourcc_str} works! Saving to: {test_path}")
                    print(f"Frame size: {frame_size}, FPS: {fps}")

                    for i, frame in enumerate(self.rgb_frames):
                        video_writer.write(frame)
                        if (i + 1) % 100 == 0:
                            print(
                                f"Writing frame {i + 1}/{len(self.rgb_frames)}",
                                end="\r",
                            )

                    video_writer.release()
                    video_path = test_path
                    print(f"\nVideo saved successfully!")
                    break
                else:
                    video_writer.release()

            except Exception as e:
                print(f"Codec {fourcc_str} failed: {e}")
                if video_writer:
                    try:
                        video_writer.release()
                    except:
                        pass
                video_writer = None
                continue

        if video_path is None:
            print("\nWarning: All codecs failed, saving as images instead...")
            self.save_as_images(output_dir, ts)

    def save_as_images(self, output_dir, ts):
        img_dir = os.path.join(output_dir, f"frames_{ts}")
        os.makedirs(img_dir, exist_ok=True)

        print(f"Saving frames as images to: {img_dir}")

        for i, frame in enumerate(self.rgb_frames):
            img_path = os.path.join(img_dir, f"frame_{i:05d}.jpg")
            cv2.imwrite(img_path, frame)
            if (i + 1) % 100 == 0:
                print(f"Saving image {i + 1}/{len(self.rgb_frames)}", end="\r")

        print(f"\nSaved {len(self.rgb_frames)} images!")

    def save_pointclouds(self):
        if not self.pointclouds:
            print("\nNo pointcloud data to save!")
            return

        output_dir = "test_recordings"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pc_path = os.path.join(output_dir, f"pointclouds_{ts}.npy")

        print(f"\nSaving pointclouds to: {pc_path}")
        print(f"Total pointcloud frames: {len(self.pointclouds)}")

        np.save(pc_path, np.array(self.pointclouds, dtype=object))

        print("Pointclouds saved successfully!")

    def save_joints(self):
        if not self.joints_data:
            print("\nNo joint data to save!")
            return

        output_dir = "test_recordings"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        joints_path = os.path.join(output_dir, f"joints_{ts}.json")

        print(f"\nSaving joints to: {joints_path}")
        print(f"Total joint frames: {len(self.joints_data)}")

        with open(joints_path, "w") as f:
            json.dump(self.joints_data, f, indent=2)

        print("Joints saved successfully!")

    def save_gripper_distances(self):
        if not self.gripper_distances:
            print("\nNo gripper distance data to save!")
            return

        output_dir = "test_recordings"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        gripper_path = os.path.join(output_dir, f"gripper_distances_{ts}.csv")

        print(f"\nSaving gripper distances to: {gripper_path}")
        print(f"Total gripper frames: {len(self.gripper_distances)}")

        with open(gripper_path, "w") as f:
            f.write("timestamp,distance\n")
            for data in self.gripper_distances:
                f.write(f"{data['timestamp']},{data['distance']}\n")

        print("Gripper distances saved successfully!")

    def save_summary(self):
        output_dir = "test_recordings"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_path = os.path.join(output_dir, f"summary_{ts}.txt")

        print(f"\nSaving summary to: {summary_path}")

        with open(summary_path, "w") as f:
            f.write("=" * 60 + "\n")
            f.write("Recording Summary\n")
            f.write("=" * 60 + "\n\n")
            f.write(
                f"Start time: {datetime.fromtimestamp(self.start_time) if self.start_time else 'N/A'}\n"
            )
            f.write(f"End time: {datetime.fromtimestamp(time.time())}\n")
            f.write(
                f"Duration: {(time.time() - self.start_time) if self.start_time else 0:.2f} seconds\n\n"
            )
            f.write(f"Total RGB frames: {len(self.rgb_frames)}\n")
            f.write(f"Total pointcloud frames: {len(self.pointclouds)}\n")
            f.write(f"Total joint frames: {len(self.joints_data)}\n")
            f.write(f"Total gripper frames: {len(self.gripper_distances)}\n\n")

            if self.rgb_frames:
                height, width, channels = self.rgb_frames[0].shape
                f.write(f"Frame resolution: {width}x{height}\n")
                f.write(f"Frame channels: {channels}\n")

            if self.pointclouds:
                pc = self.pointclouds[0]
                f.write(f"Pointcloud shape: {pc.shape}\n")

            if self.joints_data:
                joints = self.joints_data[0]["joints"]
                f.write(f"\nJoint names: {', '.join([j['name'] for j in joints])}\n")

        print("Summary saved successfully!")


async def test_replay_api():
    print("\n=== Testing Replay API ===")

    base_url = "http://localhost:8080"

    async with aiohttp.ClientSession() as session:
        print("\n1. Getting recordings list...")
        try:
            async with session.get(f"{base_url}/api/recordings") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   Recordings: {data.get('files', [])}")
                else:
                    print(f"   Error: {resp.status}")
        except Exception as e:
            print(f"   Failed: {e}")

        print("\n2. Setting mode to replay...")
        try:
            async with session.post(
                f"{base_url}/api/mode/set", json={"mode": "replay"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   Mode set: {data.get('mode')}")
                else:
                    print(f"   Error: {resp.status}")
        except Exception as e:
            print(f"   Failed: {e}")

        print("\n3. Getting replay status...")
        try:
            async with session.get(f"{base_url}/api/replay/status") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   Status: {data}")
                else:
                    print(f"   Error: {resp.status}")
        except Exception as e:
            print(f"   Failed: {e}")

        print("\n4. Resetting mode to realtime...")
        try:
            async with session.post(
                f"{base_url}/api/mode/set", json={"mode": "realtime"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   Mode reset: {data.get('mode')}")
                else:
                    print(f"   Error: {resp.status}")
        except Exception as e:
            print(f"   Failed: {e}")


async def main():
    print("=" * 60)
    print("SODA Recording & Replay Test Script")
    print("=" * 60)

    print("\nChecking if server is running...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://localhost:8080/urdf", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    print("Server is running!")
                else:
                    print("Server responded but with unexpected status")
    except Exception as e:
        print(f"Server is not running or not accessible: {e}")
        print("\nPlease start server first:")
        print("  cd soda_server")
        print("  uv run python main.py")
        sys.exit(1)

    recorder = TestRecorder()

    try:
        await recorder.connect_to_server()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")

    print("\n" + "=" * 60)
    await test_replay_api()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda sig, frame: sys.exit(0))

    asyncio.run(main())
