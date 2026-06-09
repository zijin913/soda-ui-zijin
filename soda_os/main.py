#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
SODA OS - Main Entry Point
==========================

Unified entry point for starting the SODA OS system.

Usage:
    # Start with default settings
    python -m soda_os.main

    # Start with custom port
    python -m soda_os.main --port 8080

    # Start in simulation mode
    python -m soda_os.main --mode sim

    # Start with config file
    python -m soda_os.main --config /path/to/config.yaml

Architecture:
    main.py
        └── Shell (FastAPI server)
                ├── REST API (/robot/*, /camera/*)
                ├── WebSocket (/ws/state, /ws/control)
                └── MJPEG Stream (/camera/stream)
            └── Services
                    ├── RobotService / DualArmRobotService
                    └── CameraService
                └── Core (Kinematics, Dynamics, Planning)
                └── Drivers (Real/Sim)
                └── Hardware (ZMQ Servers)
"""

import argparse
import sys
from pathlib import Path


def main():
    """Main entry point for SODA OS."""
    parser = argparse.ArgumentParser(
        description="SODA OS - Robot Operating System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m soda_os.main                    # Start with defaults
    python -m soda_os.main --port 8080        # Custom port
    python -m soda_os.main --mode sim         # Simulation mode
    python -m soda_os.main --reload           # Dev mode with hot reload
        """
    )

    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind (default: 0.0.0.0)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to bind (default: 8080)"
    )

    parser.add_argument(
        "--mode",
        type=str,
        choices=["real", "sim"],
        default="real",
        help="Operation mode: 'real' for hardware, 'sim' for simulation (default: real)"
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to configuration file (YAML or JSON)"
    )

    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable hot reload for development"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["debug", "info", "warning", "error"],
        default="info",
        help="Log level (default: info)"
    )

    args = parser.parse_args()

    # Import here to avoid slow startup for --help
    import uvicorn
    from .config import ConfigManager
    from .shell.server import create_app

    # Load configuration
    config = ConfigManager()

    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            if config_path.suffix in (".yaml", ".yml"):
                config.load("user", str(config_path))
            elif config_path.suffix == ".json":
                config.load("user", str(config_path))
            else:
                print(f"Warning: Unknown config format: {config_path.suffix}")

    # Set mode in config — top-level + per-namespace. The shell lifespan
    # reads top-level ``mode``; per-namespace copies are kept so anything
    # else reading ``robot.mode`` / ``camera.mode`` still works.
    config.set("mode", args.mode)
    config.set("robot.mode", args.mode)
    config.set("camera.mode", args.mode)

    # Print startup banner
    print()
    print("=" * 60)
    print("  ____   ___  ____    _      ___  ____  ")
    print(" / ___| / _ \\|  _ \\  / \\    / _ \\/ ___| ")
    print(" \\___ \\| | | | | | |/ _ \\  | | | \\___ \\ ")
    print("  ___) | |_| | |_| / ___ \\ | |_| |___) |")
    print(" |____/ \\___/|____/_/   \\_\\ \\___/|____/ ")
    print()
    print(f"  Mode: {args.mode.upper()}")
    print(f"  Host: http://{args.host}:{args.port}")
    print(f"  Docs: http://{args.host}:{args.port}/docs")
    print("=" * 60)
    print()

    # Create app with config
    app = create_app(config=config)

    # Run server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
