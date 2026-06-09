#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Teleop ingestion WebSocket — /ws/teleop
=======================================

High-rate dual-arm joint-target ingestion. The backend owns the single
shared ZMQ robot client; this endpoint lets an external controller
(``scripts/teleop_quest.py``, after P2) stream its computed joint targets
to that single client. Because UI jog, this teleop stream, and the replay
playback task all call ``set_cmds`` on the SAME client, coexistence is
"last-writer-wins" with no sequence-number conflict.

Client → Server (JSON text OR msgpack binary), per message::

    {"left": [q0..q6], "right": [q0..q6]}   # either arm optional; 7 = 6 arm + gripper

Send only while you want to drive (e.g. Quest clutch engaged); stop sending
to release control back to UI jog.
"""

from __future__ import annotations

import json
from typing import Dict

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

try:
    import msgpack
    HAS_MSGPACK = True
except ImportError:
    HAS_MSGPACK = False

_ARMS = ("left", "right")


def get_teleop_websocket_handler(app):
    """Create the /ws/teleop handler bound to app state."""

    async def teleop_websocket(websocket: WebSocket):
        await websocket.accept()
        dual = getattr(app.state, "dual", None)
        client = getattr(getattr(dual, "left", None), "_client", None) if dual is not None else None
        if client is None:
            print("[Teleop WS] Error: robot client not available")
            await websocket.close()
            return
        print("[Teleop WS] Client connected")
        # Re-baseline the command sequence: the teleop process opens its own
        # ZMQ state-reader clients, whose seq_clear() on connect resets the
        # robot server's shared command counter and can make THIS (backend)
        # command client's sends get rejected → arm unresponsive, then a big
        # accumulated jump when it recovers. Reset so commands are accepted now.
        try:
            if hasattr(client, "reset_cmd_seq"):
                client.reset_cmd_seq()
        except Exception as e:
            print(f"[Teleop WS] reset_cmd_seq failed: {e}")
        # Tell the legacy /ws broadcast to shed its heavy per-frame work
        # (camera JPEG + point cloud) while teleop is streaming, so it doesn't
        # starve this command path on the shared event loop. Ref-counted in
        # case multiple teleop clients connect.
        app.state.teleop_clients = getattr(app.state, "teleop_clients", 0) + 1
        app.state.teleop_active = True
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break

                data = None
                if msg.get("text") is not None:
                    try:
                        data = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        continue
                elif msg.get("bytes") is not None and HAS_MSGPACK:
                    try:
                        data = msgpack.unpackb(msg["bytes"], raw=False)
                    except Exception:
                        continue
                if not isinstance(data, dict):
                    continue

                cmds: Dict[str, np.ndarray] = {}
                for side in _ARMS:
                    q = data.get(side)
                    if q is not None:
                        cmds[side] = np.asarray(q, dtype=np.float64)
                if not cmds:
                    continue
                try:
                    client.set_cmds(cmds)
                except Exception as e:
                    print(f"[Teleop WS] set_cmds failed: {e}")
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"[Teleop WS] error: {e}")
        finally:
            app.state.teleop_clients = max(0, getattr(app.state, "teleop_clients", 1) - 1)
            app.state.teleop_active = app.state.teleop_clients > 0
            print("[Teleop WS] Client disconnected")

    return teleop_websocket
