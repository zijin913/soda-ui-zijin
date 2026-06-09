"""
Controllers module — pluggable control interfaces for SODA OS.

All controllers implement the same ``Controller`` ABC, allowing seamless
switching between teleop, policy inference, and trajectory replay.

Currently available (bimanual):
- ``QuestVIOController``: Meta Quest 3 controller-based 6-DOF teleop.

Other controllers from the single-arm soda-zijin lineage (IPhoneVIO,
SO101Leader, Policy, Replay) are not yet migrated to soda-bimanual.
"""

from .base import Controller
from .quest_vio import (
    QuestVIOController,
    R_REMAP_QUEST_DEFAULT,
    R_CORR_QUEST_DEFAULT,
    ROT_SIGN_FLIP_DEFAULT,
)

__all__ = [
    "Controller",
    "QuestVIOController",
    "R_REMAP_QUEST_DEFAULT",
    "R_CORR_QUEST_DEFAULT",
    "ROT_SIGN_FLIP_DEFAULT",
]
