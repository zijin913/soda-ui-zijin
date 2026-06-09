#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Camera API Schemas
==================

Pydantic models for camera API request/response validation.
"""

from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field


class CameraIntrinsicsResponse(BaseModel):
    """Camera intrinsics response."""
    fx: float
    fy: float
    cx: float
    cy: float
    width: Optional[int] = None
    height: Optional[int] = None


class PixelTo3DRequest(BaseModel):
    """Request to convert pixel to 3D point."""
    u: float = Field(..., description="Pixel X coordinate")
    v: float = Field(..., description="Pixel Y coordinate")
    depth: Optional[float] = Field(None, description="Depth (auto if None)")


class PixelTo3DResponse(BaseModel):
    """3D point response."""
    success: bool
    point_camera: Optional[List[float]] = None  # [x, y, z] in camera frame
    point_base: Optional[List[float]] = None  # [x, y, z] in robot base frame
    depth: Optional[float] = None
    message: str = ""


class FrameInfoResponse(BaseModel):
    """Camera frame info (metadata only, not image data)."""
    width: int
    height: int
    has_depth: bool
    timestamp: float


class PointCloudRequest(BaseModel):
    """Request for point cloud."""
    downsample: int = Field(1, description="Downsampling factor")
    transform_to_base: bool = Field(False, description="Transform to robot base frame")


class CalibrationInfoResponse(BaseModel):
    """Hand-eye calibration info."""
    is_loaded: bool
    resolution: Optional[Dict[str, int]] = None
    position_error_mm: Optional[float] = None
    orientation_error_deg: Optional[float] = None
    method: Optional[str] = None
