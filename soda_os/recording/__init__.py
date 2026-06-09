"""Replay for dual-arm sessions.

Recording lives in teleop (scripts/teleop_quest.py → soda_os/data/
TrajectoryRecorder, HDF5). This package provides the replay reader:
- Hdf5ReplayManager: raw teleop HDF5 episodes (recordings/hdf5/<ts>/)
"""

from .hdf5_replay_manager import Hdf5ReplayManager

__all__ = ["Hdf5ReplayManager"]
