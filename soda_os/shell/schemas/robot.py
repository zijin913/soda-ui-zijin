#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Robot API Schemas (dual-arm)
============================

Pydantic models for robot API request/response validation. The shell
backend is dual-arm only — request bodies use the ``arms`` dict pattern
to address one or both arms in a single call::

    {"arms": {"left": {...}, "right": {...}}}     # both arms
    {"arms": {"left": {...}}}                      # left only

Read endpoints likewise return ``{"left": ..., "right": ...}`` shape.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# ==================== Per-arm request payloads ====================

class MoveToPositionRequest(BaseModel):
    """Per-arm: move end-effector to (x, y, z)."""
    x: float = Field(..., description="X position in meters")
    y: float = Field(..., description="Y position in meters")
    z: float = Field(..., description="Z position in meters")
    duration: Optional[float] = Field(None, description="Motion duration in seconds")


class MoveToJointsRequest(BaseModel):
    """Per-arm: move to joint configuration."""
    joints: List[float] = Field(..., description="Joint angles in radians")
    duration: Optional[float] = Field(None, description="Motion duration in seconds")


class MoveToPixelRequest(BaseModel):
    """Per-arm: move to a point specified by pixel coordinates."""
    u: float = Field(..., description="Pixel X coordinate")
    v: float = Field(..., description="Pixel Y coordinate")
    depth: Optional[float] = Field(None, description="Depth in meters (auto if None)")
    duration: Optional[float] = Field(None, description="Motion duration in seconds")


class HomeRequest(BaseModel):
    """Dual-arm homing. Both arms share one home (identical hardware).

    Body is optional — POST ``/robot/home`` with no body keeps the
    backend-configured home. Supply ``home_position`` to pin an explicit
    target (e.g. teleop imposing its own ``HOME_JOINTS`` so there is a single
    source of truth) and/or ``duration`` to override the motion time.
    """
    home_position: Optional[List[float]] = Field(
        None, description="Arm joint angles (rad) to home to; overrides backend config"
    )
    duration: Optional[float] = Field(None, description="Motion duration in seconds")


class GripperRequest(BaseModel):
    """Per-arm: control gripper."""
    action: str = Field(..., description="'open' or 'close'")
    angle: Optional[float] = Field(None, description="Specific angle in radians")


# ==================== Dual-arm wrappers ====================

class DualMoveToPositionRequest(BaseModel):
    """Drive one or both arms to a 3D position.

    ``arms`` maps "left" / "right" to that arm's per-arm payload. Omit an
    arm to leave it untouched.
    """
    arms: Dict[str, MoveToPositionRequest]


class DualMoveToJointsRequest(BaseModel):
    """Drive one or both arms to a joint configuration."""
    arms: Dict[str, MoveToJointsRequest]


class DualMoveToPixelRequest(BaseModel):
    """Drive one or both arms toward a pixel target on that arm's camera."""
    arms: Dict[str, MoveToPixelRequest]


class DualGripperRequest(BaseModel):
    """Open/close grippers on one or both arms."""
    arms: Dict[str, GripperRequest]


class PickAndPlaceRequest(BaseModel):
    """Single-arm pick-and-place driven by one named arm."""
    arm: str = Field("left", description="Which arm executes the task")
    pick_x: float
    pick_y: float
    pick_z: float
    place_x: float
    place_y: float
    place_z: float
    approach_height: float = Field(0.05, description="Height above object for approach")


# ==================== Response Schemas ====================

class RobotStateResponse(BaseModel):
    """Per-arm robot state response."""
    joint_positions: List[float]
    joint_velocities: List[float]
    joint_torques: List[float]
    ee_position: List[float]   # [x, y, z]
    ee_rotation: List[List[float]]  # 3x3 matrix
    timestamp: float


class DualRobotStateResponse(BaseModel):
    """Read-state response keyed by arm name."""
    arms: Dict[str, RobotStateResponse]


class JointLimitsResponse(BaseModel):
    """Per-arm joint limits response."""
    lower: List[float]
    upper: List[float]
    num_joints: int


class DualJointLimitsResponse(BaseModel):
    """Per-arm joint limits keyed by arm name."""
    arms: Dict[str, JointLimitsResponse]


class OperationResponse(BaseModel):
    """Generic operation response (legacy single-arm flavour).

    For dual-arm motion endpoints prefer :class:`DualOperationResponse` —
    it keeps per-arm success / message instead of collapsing both into one.
    """
    success: bool
    message: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)


class DualOperationResponse(BaseModel):
    """Per-arm result of a dual-arm operation."""
    arms: Dict[str, OperationResponse]


class IKResultResponse(BaseModel):
    """Inverse kinematics result (per-arm)."""
    success: bool
    joints: Optional[List[float]] = None
    error_pos: float = 0.0
    error_ori: float = 0.0
    method: str = ""
    message: str = ""


class DualIKResultResponse(BaseModel):
    """Per-arm IK result keyed by arm name."""
    arms: Dict[str, IKResultResponse]


class TaskResultResponse(BaseModel):
    """Task execution result."""
    success: bool
    status: str
    message: str = ""
    duration: float = 0.0
    data: Dict[str, Any] = Field(default_factory=dict)
