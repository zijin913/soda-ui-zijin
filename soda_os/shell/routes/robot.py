#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Robot API Routes (dual-arm)
===========================

REST endpoints for dual-arm robot control. All read endpoints return
``{"arms": {"left": ..., "right": ...}}`` shape. Motion endpoints accept
the same shape — supply only one arm to drive just that arm.
"""

import numpy as np
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional

from ..schemas import (
    DualGripperRequest,
    DualIKResultResponse,
    DualJointLimitsResponse,
    DualMoveToJointsRequest,
    DualMoveToPixelRequest,
    DualMoveToPositionRequest,
    DualOperationResponse,
    DualRobotStateResponse,
    HomeRequest,
    IKResultResponse,
    JointLimitsResponse,
    MoveToPositionRequest,
    OperationResponse,
    RobotStateResponse,
)

router = APIRouter(prefix="/robot", tags=["robot"])


# Dependency injection placeholders — populated by server.lifespan.
# ``_dual_service`` is the :class:`DualArmRobotService` instance.
_dual_service = None

_ARMS = ("left", "right")


def get_dual_service():
    if _dual_service is None:
        raise HTTPException(status_code=503, detail="Dual robot service not initialized")
    return _dual_service


def _resolve_arm(dual, arm: str):
    if arm not in _ARMS:
        raise HTTPException(status_code=400, detail=f"Invalid arm {arm!r}; expected one of {_ARMS}")
    return getattr(dual, arm)


# ==================== State Endpoints ====================

@router.get("/state", response_model=DualRobotStateResponse)
async def get_robot_state(dual=Depends(get_dual_service)):
    """Get current state for both arms."""
    out = {}
    for arm in _ARMS:
        s = getattr(dual, arm).get_state()
        if s is None:
            raise HTTPException(status_code=500, detail=f"Failed to get state for {arm}")
        out[arm] = RobotStateResponse(
            joint_positions=s.joint_positions.tolist(),
            joint_velocities=s.joint_velocities.tolist(),
            joint_torques=s.joint_torques.tolist(),
            ee_position=s.ee_position.tolist(),
            ee_rotation=s.ee_rotation.tolist(),
            timestamp=s.timestamp,
        )
    return DualRobotStateResponse(arms=out)


@router.get("/joints")
async def get_joint_positions(dual=Depends(get_dual_service)):
    """Get current joint positions for both arms."""
    out = {}
    for arm in _ARMS:
        q = getattr(dual, arm).get_joint_positions()
        if q is None:
            raise HTTPException(status_code=500, detail=f"Failed to get joints for {arm}")
        out[arm] = q.tolist()
    return {"arms": out}


@router.get("/ee_position")
async def get_ee_position(dual=Depends(get_dual_service)):
    """Get current end-effector position for both arms."""
    out = {}
    for arm in _ARMS:
        p = getattr(dual, arm).get_ee_position()
        if p is None:
            raise HTTPException(status_code=500, detail=f"Failed to get EE position for {arm}")
        out[arm] = p.tolist()
    return {"arms": out}


@router.get("/limits", response_model=DualJointLimitsResponse)
async def get_joint_limits(dual=Depends(get_dual_service)):
    """Get joint position limits for both arms (typically identical)."""
    out = {}
    for arm in _ARMS:
        limits = getattr(dual, arm).get_joint_limits()
        if limits is None:
            raise HTTPException(status_code=500, detail=f"Failed to get limits for {arm}")
        lower, upper = limits
        out[arm] = JointLimitsResponse(
            lower=lower.tolist(),
            upper=upper.tolist(),
            num_joints=len(lower),
        )
    return DualJointLimitsResponse(arms=out)


# ==================== Motion Endpoints ====================

@router.post("/move/position", response_model=DualOperationResponse)
async def move_to_position(
    request: DualMoveToPositionRequest,
    dual=Depends(get_dual_service),
):
    """Drive any subset of arms to a 3D position.

    Use ``arms = {"left": {...}}`` to move only the left arm, etc. The
    response carries per-arm success / message.
    """
    arms_out = {}
    for arm_name, payload in request.arms.items():
        robot = _resolve_arm(dual, arm_name)
        target = np.array([payload.x, payload.y, payload.z])
        exec_success, ik_success = robot.move_to_point(target, payload.duration)
        arms_out[arm_name] = OperationResponse(
            success=exec_success,
            message="Move completed" if exec_success else "Move failed",
            data={"ik_success": ik_success},
        )
    return DualOperationResponse(arms=arms_out)


@router.post("/move/joints", response_model=DualOperationResponse)
async def move_to_joints(
    request: DualMoveToJointsRequest,
    dual=Depends(get_dual_service),
):
    """Drive any subset of arms to a joint configuration."""
    arms_out = {}
    for arm_name, payload in request.arms.items():
        robot = _resolve_arm(dual, arm_name)
        target = np.array(payload.joints)
        success = robot.move_to_joints(target, payload.duration)
        arms_out[arm_name] = OperationResponse(
            success=success,
            message="Joint move completed" if success else "Joint move failed",
        )
    return DualOperationResponse(arms=arms_out)


@router.post("/move/pixel", response_model=DualOperationResponse)
async def move_to_pixel(
    request: DualMoveToPixelRequest,
    dual=Depends(get_dual_service),
):
    """Per-arm: convert a pixel on each arm's wrist camera to a 3D target.

    Each arm uses its own hand-eye calibration intrinsics. Depth must be
    supplied in the payload (we can't read it without a CameraService here).
    """
    arms_out = {}
    for arm_name, payload in request.arms.items():
        robot = _resolve_arm(dual, arm_name)
        if not robot.calibration.is_loaded:
            arms_out[arm_name] = OperationResponse(
                success=False, message="Calibration not loaded", data={"ik_success": False},
            )
            continue
        K = robot.calibration.intrinsics
        if K is None:
            arms_out[arm_name] = OperationResponse(
                success=False, message="Camera intrinsics not available", data={"ik_success": False},
            )
            continue
        if payload.depth is None:
            arms_out[arm_name] = OperationResponse(
                success=False, message="Depth value required", data={"ik_success": False},
            )
            continue
        exec_success, ik_success = robot.move_to_pixel(
            payload.u, payload.v, payload.depth, K, payload.duration,
        )
        arms_out[arm_name] = OperationResponse(
            success=exec_success,
            message="Move completed" if exec_success else "Move failed",
            data={"ik_success": ik_success},
        )
    return DualOperationResponse(arms=arms_out)


@router.post("/home", response_model=OperationResponse)
async def go_home(req: Optional[HomeRequest] = None, dual=Depends(get_dual_service)):
    """Move BOTH arms to home position in parallel.

    Body is optional. Supply ``home_position`` (and/or ``duration``) to pin an
    explicit home — this is how teleop imposes its own ``HOME_JOINTS`` so the
    executing backend and the verifying client share one home definition.
    """
    home_position = np.asarray(req.home_position) if (req and req.home_position is not None) else None
    duration = req.duration if req else None
    success = dual.go_home(duration=duration, home_position=home_position)
    return OperationResponse(
        success=success,
        message="Both arms homed" if success else "Home failed",
    )


@router.post("/stop", response_model=OperationResponse)
async def stop_robot(dual=Depends(get_dual_service)):
    """Stop BOTH arms simultaneously."""
    success = dual.stop()
    return OperationResponse(
        success=success,
        message="Both arms stopped" if success else "Stop failed",
    )


# ==================== Gripper Endpoints ====================

@router.post("/gripper", response_model=DualOperationResponse)
async def control_gripper(
    request: DualGripperRequest,
    dual=Depends(get_dual_service),
):
    """Open/close grippers on any subset of arms."""
    arms_out = {}
    for arm_name, payload in request.arms.items():
        robot = _resolve_arm(dual, arm_name)
        if payload.action == "open":
            ok = robot.open_gripper() if hasattr(robot, "open_gripper") else True
        elif payload.action == "close":
            ok = robot.close_gripper() if hasattr(robot, "close_gripper") else True
        else:
            arms_out[arm_name] = OperationResponse(
                success=False, message=f"Invalid action: {payload.action}",
            )
            continue
        arms_out[arm_name] = OperationResponse(
            success=ok, message=f"Gripper {payload.action}" if ok else "Gripper failed",
        )
    return DualOperationResponse(arms=arms_out)


# ==================== IK Endpoints ====================

@router.post("/ik/solve", response_model=DualIKResultResponse)
async def solve_ik(
    request: DualMoveToPositionRequest,
    dual=Depends(get_dual_service),
):
    """Per-arm: solve IK without moving. Returns one IK result per requested arm."""
    arms_out = {}
    for arm_name, payload in request.arms.items():
        robot = _resolve_arm(dual, arm_name)
        if robot.kinematics is None:
            arms_out[arm_name] = IKResultResponse(success=False, message="Kinematics not initialized")
            continue
        target = np.array([payload.x, payload.y, payload.z])
        q_init = robot.get_joint_positions()
        result = robot.kinematics.solve_ik(target, None, q_init)
        arms_out[arm_name] = IKResultResponse(
            success=result.success,
            joints=result.joints.tolist() if result.joints is not None else None,
            error_pos=result.error_pos,
            error_ori=result.error_ori,
            method=result.method,
            message=result.message,
        )
    return DualIKResultResponse(arms=arms_out)
