#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Test Services with Simulation
==============================

Test DualArmRobotService and CameraService against the MuJoCo simulation.

The sim/real drivers expose a dict-of-arms schema; the services slice that
into per-arm / per-camera handles. This test mirrors how
``soda_os/shell/server.py`` wires things up:

  - one DualArmRobotService (two per-arm RobotService instances over a
    shared robot driver)
  - left/right/side CameraService instances over a shared camera driver

Requires the Firefly Y6 dual MuJoCo server running:
    python launchers/launch_servers.py --mode sim
"""

import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from soda_os.drivers import DriverFactory
from soda_os.services import CameraService
from soda_os.services.dual_arm_service import DualArmRobotService

# Shared sim config — same shape DualArmRobotService.from_config expects.
SIM_CONFIG = {
    "mode": "sim",
    "sim": {
        "ip": "127.0.0.1",
        "port": 12345,
    },
    "urdf": "firefly_y6_gr100",
    "end_effector_frame": "link_6",
}

ARMS = ("left", "right")
CAMERAS = ("left", "right", "side")


def _print_arm_state(arm, state):
    if state is None:
        print(f"  [{arm}] state: None")
        return
    print(f"  [{arm}] joint_positions: {state.joint_positions[:6]}")
    print(f"  [{arm}] joint_velocities: {state.joint_velocities[:6]}")
    print(f"  [{arm}] ee_position: {state.ee_position}")
    print(f"  [{arm}] timestamp: {state.timestamp:.3f}")


def test_dual_arm_service():
    """Test DualArmRobotService with simulation."""
    print("=" * 50)
    print("Testing DualArmRobotService with Simulation")
    print("=" * 50)

    service = DualArmRobotService.from_config(config=SIM_CONFIG)

    print("\n[1] Connecting both arms...")
    if not service.connect():
        print("Failed to connect! Is the MuJoCo server running?")
        return False
    print("Connected!")

    print("\n[2] Getting dual-arm state...")
    states = service.get_states()
    for arm in ARMS:
        _print_arm_state(arm, states.get(arm))

    print("\n[3] Getting dual-arm state (parallel)...")
    states_par = service.get_states_parallel()
    for arm in ARMS:
        ok = states_par.get(arm) is not None
        print(f"  [{arm}] state: {'OK' if ok else 'None'}")

    print("\n[4] Getting joint positions (both arms)...")
    joints = service.get_joint_positions()
    for arm in ARMS:
        q = joints.get(arm)
        if q is not None:
            print(f"  [{arm}] positions: {q[:6]}")
        else:
            print(f"  [{arm}] positions: None")

    print("\n[5] Getting EE positions (both arms)...")
    ee = service.get_ee_positions()
    for arm in ARMS:
        ee_pos = ee.get(arm)
        print(f"  [{arm}] ee_position: {ee_pos}")

    print("\n[6] Disconnecting...")
    service.disconnect()
    print(f"  Connected: {service.is_connected}")

    print("\nDualArmRobotService test PASSED!")
    return True


def _test_one_camera(service, cam_name):
    """Exercise a single CameraService slice; return True if usable."""
    print(f"\n--- camera: {cam_name} ---")

    print("  [1] Connecting...")
    if not service.connect():
        print("  Failed to connect!")
        return False
    print("  Connected!")

    # Warm-up: in realtime sim the first read right after connect returns
    # None because no frame has been rendered/queued yet (the driver only
    # caches frames once seen). Poll briefly so the image path below
    # actually exercises real frames instead of a cold-start miss.
    print("  [1b] Warming up frame stream...")
    for _ in range(40):  # ~2s @ 50ms
        if service.get_rgb(use_cache=False) is not None:
            break
        time.sleep(0.05)

    print("  [2] Getting intrinsics...")
    intrinsics = service.intrinsics
    if intrinsics is not None:
        print(f"    Intrinsics:\n{intrinsics}")
    else:
        print("    No intrinsics available (cam may be absent in sim)")

    print("  [3] Getting RGB image...")
    rgb = service.get_rgb()
    if rgb is not None:
        print(f"    RGB shape: {rgb.shape}, dtype: {rgb.dtype}")
    else:
        print("    RGB: None (cam absent or no data yet)")

    print("  [4] Getting depth image...")
    depth = service.get_depth()
    if depth is not None:
        print(f"    Depth shape: {depth.shape}, dtype: {depth.dtype}")
        print(f"    Depth range: [{depth.min():.3f}, {depth.max():.3f}] m")
    else:
        print("    Depth: None (cam absent or no data yet)")

    print("  [5] Getting frame...")
    frame = service.get_frame()
    if frame is not None:
        print(f"    Frame RGB shape: {frame.rgb.shape}")
        if frame.depth is not None:
            print(f"    Frame depth shape: {frame.depth.shape}")

    print("  [6] Pixel to 3D (center of image)...")
    if intrinsics is not None and depth is not None:
        h, w = depth.shape
        u, v = w // 2, h // 2
        point = service.pixel_to_3d(u, v)
        if point is not None:
            print(f"    Pixel ({u}, {v}) -> 3D: {point}")
        else:
            print(f"    No valid depth at ({u}, {v})")

    return True


def test_camera_services():
    """Test per-camera CameraService slices over a shared driver."""
    print("\n" + "=" * 50)
    print("Testing CameraService (left/right/side) with Simulation")
    print("=" * 50)

    # One shared camera driver, sliced into per-camera services — same
    # wiring as soda_os/shell/server.py.
    cam_factory = DriverFactory(
        mode="sim",
        config={
            "sim": SIM_CONFIG["sim"],
            "robot": {},
            "camera": {},
        },
    )
    shared_cam_driver = cam_factory.create_camera_driver()

    services = {
        name: CameraService(camera_client=shared_cam_driver, cam_name=name)
        for name in CAMERAS
    }

    ok_any = False
    for name in CAMERAS:
        if _test_one_camera(services[name], name):
            ok_any = True

    print("\n[*] Disconnecting cameras...")
    # All services share one driver; disconnecting once tears it down.
    services["left"].disconnect()
    print(f"  Connected: {services['left'].is_connected}")

    if ok_any:
        print("\nCameraService test PASSED!")
    else:
        print("\nCameraService test FAILED (no camera connected)!")
    return ok_any


if __name__ == "__main__":
    print("Services Simulation Test")
    print("Make sure the Firefly Y6 dual MuJoCo server is running:")
    print("  python launchers/launch_servers.py --mode sim")
    print()

    try:
        success1 = test_dual_arm_service()
        if success1:
            success2 = test_camera_services()
        else:
            success2 = False

        print("\n" + "=" * 50)
        if success1 and success2:
            print("ALL TESTS PASSED!")
        else:
            print("SOME TESTS FAILED!")
        print("=" * 50)

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
