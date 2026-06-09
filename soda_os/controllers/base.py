"""
Controller Abstract Base Class.

All controllers (teleop, policy, replay) implement this interface.
This allows the demo collection script and deployment script to work
with any controller without modification.

Design decisions:
- Synchronous interface (no async) — teleop loops are inherently synchronous
- get_action() returns a dict with both joint and cartesian targets
  (matching the Franka/EVA HDF5 data format)
- observation dict keys match HDF5 observation/robot_state/* paths

Adapted from EVA's Controller base class (eva/controllers/controller.py).
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

import numpy as np


class Controller(ABC):
    """
    Abstract base class for all robot controllers.

    Subclasses must implement get_action() and reset().

    Usage:
        controller = IPhoneVIOController(...)
        controller.reset()

        while running:
            obs = get_observation_from_robot()
            action = controller.get_action(obs)
            if action is not None:
                send_action_to_robot(action)
    """

    @abstractmethod
    def get_action(self, observation: dict) -> Optional[dict]:
        """
        Compute action from current observation.

        Args:
            observation: dict with keys:
                "joint_positions": np.ndarray (6,)    — current joint angles (rad)
                "joint_velocities": np.ndarray (6,)   — current joint velocities (rad/s)
                "cartesian_position": np.ndarray (6,)  — EE pose [x,y,z,rx,ry,rz] in base frame
                "gripper_position": float              — gripper state (0=closed, 1=open)
                "images": dict                         — {"hand_camera": (H,W,3), "side_camera": (H,W,3)}
                "timestamp": float                     — current time (seconds)

        Returns:
            action dict, or None if no action this step:
                "joint_position": np.ndarray (6,)      — target joint angles (rad)
                "cartesian_position": np.ndarray (6,)   — target EE pose [x,y,z,rx,ry,rz]
                "gripper_position": float               — target gripper (0=closed, 1=open)

            Callers should handle None gracefully (skip this step).
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """
        Reset controller state.

        Called at the start of each episode. For teleop controllers,
        this typically recenters the input device reference frame.
        For policy controllers, this clears the action queue.
        """
        ...

    def get_info(self) -> Dict[str, Any]:
        """
        Return controller metadata and status.

        Returns:
            dict with at least:
                "name": str              — controller class name
                "controller_on": bool    — whether controller is active
                "movement_enabled": bool — whether movement commands are being sent
                "success": bool          — episode marked as success
                "failure": bool          — episode marked as failure
        """
        return {
            "name": self.__class__.__name__,
            "controller_on": True,
            "movement_enabled": True,
            "success": False,
            "failure": False,
        }

    def close(self) -> None:
        """Release resources (network connections, threads, etc.)."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
