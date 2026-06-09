#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
API Schemas
===========

Pydantic schemas for API request/response validation.
"""

from .robot import (
    MoveToPositionRequest,
    MoveToJointsRequest,
    MoveToPixelRequest,
    GripperRequest,
    HomeRequest,
    PickAndPlaceRequest,
    DualMoveToPositionRequest,
    DualMoveToJointsRequest,
    DualMoveToPixelRequest,
    DualGripperRequest,
    RobotStateResponse,
    DualRobotStateResponse,
    OperationResponse,
    DualOperationResponse,
    IKResultResponse,
    DualIKResultResponse,
    TaskResultResponse,
    JointLimitsResponse,
    DualJointLimitsResponse,
)

from .camera import (
    CameraIntrinsicsResponse,
    PixelTo3DRequest,
    PixelTo3DResponse,
    FrameInfoResponse,
    PointCloudRequest,
    CalibrationInfoResponse,
)

__all__ = [
    # Robot (per-arm payloads)
    "MoveToPositionRequest",
    "MoveToJointsRequest",
    "MoveToPixelRequest",
    "GripperRequest",
    "HomeRequest",
    "PickAndPlaceRequest",
    # Robot (dual-arm wrappers)
    "DualMoveToPositionRequest",
    "DualMoveToJointsRequest",
    "DualMoveToPixelRequest",
    "DualGripperRequest",
    # Robot responses
    "RobotStateResponse",
    "DualRobotStateResponse",
    "OperationResponse",
    "DualOperationResponse",
    "IKResultResponse",
    "DualIKResultResponse",
    "TaskResultResponse",
    "JointLimitsResponse",
    "DualJointLimitsResponse",
    # Camera
    "CameraIntrinsicsResponse",
    "PixelTo3DRequest",
    "PixelTo3DResponse",
    "FrameInfoResponse",
    "PointCloudRequest",
    "CalibrationInfoResponse",
]
