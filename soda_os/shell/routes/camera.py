#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Camera API Routes (dual-arm)
============================

Read endpoints that return per-frame metadata or intrinsics use the
``{"arms": {"left": ..., "right": ...}}`` shape. Binary streams (RGB,
depth, MJPEG) carry a single image and accept ``?cam=left|right`` to
select the wrist camera.
"""

import io

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from ..schemas import (
    CalibrationInfoResponse,
    CameraIntrinsicsResponse,
    FrameInfoResponse,
    PixelTo3DRequest,
    PixelTo3DResponse,
)

router = APIRouter(prefix="/camera", tags=["camera"])


# Dependency injection — populated by server.lifespan.
# ``_cameras`` is a dict {"left": CameraService, "right": CameraService}.
# ``_dual_service`` is the DualArmRobotService for hand-eye / FK lookups.
_cameras = None
_dual_service = None


@router.get("/_debug")
async def camera_debug():
    """Dump runtime camera state for troubleshooting."""
    out = {}
    cams = _cameras or {}
    # Per-CameraService view
    for name, svc in cams.items():
        out[name] = {
            "service_connected": getattr(svc, "_connected", None),
            "service_intrinsics_present": getattr(svc, "_intrinsics", None) is not None,
            "cam_name": getattr(svc, "_cam_name", None),
        }
    # Underlying shared driver state
    drv = None
    for svc in cams.values():
        drv = getattr(svc, "_client", None)
        if drv is not None:
            break
    if drv is not None:
        out["_driver"] = {
            "type": type(drv).__name__,
            "connected": getattr(drv, "_connected", None),
            "clients_alive": {
                k: (v is not None) for k, v in getattr(drv, "_clients", {}).items()
            },
            "intrinsics_keys": list((getattr(drv, "_intrinsics", None) or {}).keys()),
            "fail_counts": getattr(drv, "_fail_counts", None),
        }
        # Try a fresh _collect call so we surface a live status
        try:
            res = drv.get_rgb()
            out["_live_get_rgb"] = {
                "is_none": res is None,
                "keys": list((res or {}).keys()),
                "shapes": {k: list(v.shape) for k, v in (res or {}).items()},
            }
        except Exception as e:
            out["_live_get_rgb"] = {"error": repr(e)}
    return out

_ARMS = ("left", "right")


def get_cameras():
    if _cameras is None:
        raise HTTPException(status_code=503, detail="Cameras not initialized")
    return _cameras


def get_dual_service():
    if _dual_service is None:
        raise HTTPException(status_code=503, detail="Dual robot service not initialized")
    return _dual_service


def _pick_camera(cameras, cam: str):
    if cam not in cameras:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown cam {cam!r}; available: {sorted(cameras.keys())}",
        )
    return cameras[cam]


# ==================== Image / metadata endpoints ====================

@router.get("/frame/info")
async def get_frame_info(cameras=Depends(get_cameras)):
    """Per-arm frame metadata (no image data)."""
    out = {}
    for arm in _ARMS:
        cam = cameras.get(arm)
        if cam is None:
            continue
        frame = cam.get_frame()
        if frame is None:
            raise HTTPException(status_code=500, detail=f"Failed to capture frame for {arm}")
        out[arm] = FrameInfoResponse(
            width=frame.rgb.shape[1],
            height=frame.rgb.shape[0],
            has_depth=frame.depth is not None,
            timestamp=frame.timestamp,
        )
    return {"arms": {k: v.model_dump() for k, v in out.items()}}


@router.get("/rgb")
async def get_rgb_image(
    cam: str = "left",
    format: str = "jpeg",
    quality: int = 85,
    cameras=Depends(get_cameras),
):
    """RGB image from the chosen wrist camera.

    Args:
        cam:     "left" or "right" (default "left")
        format:  "jpeg" or "png"
        quality: JPEG quality 1-100
    """
    camera = _pick_camera(cameras, cam)
    rgb = camera.get_rgb()
    if rgb is None:
        raise HTTPException(status_code=500, detail=f"Failed to capture RGB on {cam}")

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if format == "jpeg":
        _, buffer = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        media_type = "image/jpeg"
    else:
        _, buffer = cv2.imencode('.png', bgr)
        media_type = "image/png"
    return StreamingResponse(io.BytesIO(buffer.tobytes()), media_type=media_type)


@router.get("/depth")
async def get_depth_image(
    cam: str = "left",
    colorize: bool = True,
    cameras=Depends(get_cameras),
):
    """Depth image from the chosen wrist camera.

    Args:
        cam:      "left" or "right" (default "left")
        colorize: if True returns a JPEG with JET colormap; if False a 16-bit PNG (depth in mm)
    """
    camera = _pick_camera(cameras, cam)
    depth = camera.get_depth()
    if depth is None:
        raise HTTPException(status_code=500, detail=f"Failed to capture depth on {cam}")

    if colorize:
        depth_normalized = cv2.normalize(depth, None, 0, 255, cv2.NORM_MINMAX)
        depth_colored = cv2.applyColorMap(depth_normalized.astype(np.uint8), cv2.COLORMAP_JET)
        _, buffer = cv2.imencode('.jpg', depth_colored)
        media_type = "image/jpeg"
    else:
        depth_mm = (depth * 1000).astype(np.uint16)
        _, buffer = cv2.imencode('.png', depth_mm)
        media_type = "image/png"
    return StreamingResponse(io.BytesIO(buffer.tobytes()), media_type=media_type)


# ==================== Intrinsics ====================

@router.get("/intrinsics")
async def get_intrinsics(cameras=Depends(get_cameras)):
    """Per-arm camera intrinsics."""
    out = {}
    for arm in _ARMS:
        cam = cameras.get(arm)
        if cam is None:
            continue
        K = cam.intrinsics
        if K is None:
            continue
        res = cam.resolution if hasattr(cam, "resolution") else None
        out[arm] = CameraIntrinsicsResponse(
            fx=float(K[0, 0]),
            fy=float(K[1, 1]),
            cx=float(K[0, 2]),
            cy=float(K[1, 2]),
            width=res[0] if res else None,
            height=res[1] if res else None,
        )
    if not out:
        raise HTTPException(status_code=500, detail="No camera intrinsics available")
    return {"arms": {k: v.model_dump() for k, v in out.items()}}


# ==================== 3D Conversion ====================

@router.post("/pixel_to_3d", response_model=PixelTo3DResponse)
async def pixel_to_3d(
    request: PixelTo3DRequest,
    cam: str = "left",
    cameras=Depends(get_cameras),
    dual=Depends(get_dual_service),
):
    """Convert a pixel on the chosen wrist camera to a 3D point.

    Returns the point in both camera and robot base frame (the base frame
    of the arm that owns this wrist camera).
    """
    camera = _pick_camera(cameras, cam)
    robot = getattr(dual, cam)  # cam is "left"/"right" — same key for the per-arm robot

    depth = request.depth
    if depth is None:
        depth = camera.get_depth_at_pixel(int(request.u), int(request.v))
        if depth is None:
            return PixelTo3DResponse(success=False, message="Invalid depth at pixel")

    point_camera = camera.pixel_to_3d(request.u, request.v, depth)
    if point_camera is None:
        return PixelTo3DResponse(success=False, message="Failed to convert to 3D")

    point_base = None
    if robot.calibration.is_loaded and robot.transforms is not None:
        try:
            q = robot.get_joint_positions()
            if q is not None:
                T_gripper2base = robot.kinematics.forward(q)
                point_base = robot.transforms.camera_to_base(point_camera, T_gripper2base)
        except Exception:
            pass  # base-frame transform optional

    return PixelTo3DResponse(
        success=True,
        point_camera=point_camera.tolist(),
        point_base=point_base.tolist() if point_base is not None else None,
        depth=depth,
        message="OK",
    )


@router.get("/depth_at_pixel")
async def get_depth_at_pixel(
    u: int,
    v: int,
    cam: str = "left",
    cameras=Depends(get_cameras),
):
    """Depth value at a specific pixel on the chosen wrist camera."""
    camera = _pick_camera(cameras, cam)
    depth = camera.get_depth_at_pixel(u, v)
    if depth is None:
        raise HTTPException(status_code=400, detail="Invalid depth at pixel")
    return {"cam": cam, "u": u, "v": v, "depth": depth}


# ==================== Calibration ====================

@router.get("/calibration")
async def get_calibration_info(dual=Depends(get_dual_service)):
    """Per-arm hand-eye calibration status."""
    out = {}
    for arm in _ARMS:
        robot = getattr(dual, arm)
        calib = robot.calibration
        metrics = calib.metrics if calib.is_loaded else {}
        out[arm] = CalibrationInfoResponse(
            is_loaded=calib.is_loaded,
            resolution=calib.resolution if calib.is_loaded else None,
            position_error_mm=metrics.get("mean_position_error_mm"),
            orientation_error_deg=metrics.get("mean_angular_error_deg"),
            method=calib._metadata.get("method") if calib.is_loaded else None,
        )
    return {"arms": {k: v.model_dump() for k, v in out.items()}}
