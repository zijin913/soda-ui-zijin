# SODA - Agents Guide

This document provides guidelines for AI agents working on the SODA project - a robot simulation and visualization system.

## Project Overview

SODA is a real-time robot simulation and visualization platform consisting of:

- **soda_server**: Python backend server using aiohttp WebSocket
  - MuJoCo physics simulation for robot dynamics
  - Streams video frames (30 FPS)
  - Sends real-time robot joint telemetry data (angle, velocity, torque)
  - Receives joint control commands from web client
  - Located in `soda_server/`

- **soda_ui**: Vue 3 + TypeScript + Vite frontend
  - Three.js 3D robot visualization with URDF model support
  - Real-time camera panel display
  - Joint data charts and visualization
  - Interactive joint dragging (sends commands to backend)
  - Located in `soda_ui/`

## Architecture

### Backend (soda_server/)
- **main.py**: Main server entry point
  - WebSocket endpoint: `ws://localhost:8080/ws`
    - Sends MuJoCo joint states (angle, velocity, torque)
    - Receives joint control commands from client
  - HTTP endpoint: `GET /urdf` - Returns JSON with URDF file URL
  - HTTP endpoint: `POST /api/joint/set` - Sets target joint angle
  - Static file service: `GET /assets/*` - Serves URDF meshes and related assets from `public/`
  - CORS middleware enabled for cross-origin requests
  - Video streaming using OpenCV
  - MuJoCo physics simulation (6 joints)
  - Dependencies: aiohttp, opencv-python, mujoco

### Frontend (soda_ui/)
- **src/main.ts**: Vue app initialization with Pinia store
- **src/App.vue**: Main dashboard layout
  - WebSocket connection management
  - Real-time data handling (video + telemetry)
- **src/components/RobotViewport.vue**: 3D robot viewer
  - Three.js scene with OrbitControls
  - URDF model loading
  - Joint interaction and visualization helpers
- **src/components/CameraPanel.vue**: Floating camera view
- **src/components/RightSidebar.vue**: Data visualization sidebar
- **src/components/TopBar.vue**: Tool selection UI

## Commands

### Backend
```bash
cd soda_server
# Run server (assumes uv is configured)
uv run main.py
```

### Frontend
```bash
cd soda_ui
npm install      # Install dependencies
npm run dev      # Start development server
npm run build    # Build for production
npm run type-check  # TypeScript type checking
npm run lint     # Run linter (oxlint + eslint)
npm run format   # Format code with prettier
```

## Testing

### Frontend Tests
```bash
npm run test:unit   # Run Vitest unit tests
npm run test:e2e    # Run Playwright E2E tests
```

## Code Conventions

### TypeScript/Vue
- Use `<script setup>` syntax for Vue 3 components
- Follow existing component structure (template, script setup, style)
- Use composition API with ref/reactive
- Maintain type safety with TypeScript
- Follow Tailwind CSS utility-first styling approach

### Python
- Use asyncio for async operations
- WebSocket communication patterns as in main.py
- OpenCV for video processing

## Key Technical Patterns

### HTTP API
- **GET /urdf**: Returns JSON with URDF file URL
  - Response: `{"url": "http://localhost:8080/assets/xpkg_urdf_archer_l6y/xpkg_urdf_archer_l6y.urdf"}`
- **POST /api/joint/set**: Sets target joint angle for MuJoCo simulation
  - Request body: `{"joint_id": 1, "angle": 1.5}`
- **GET /assets/***: Serves static files (URDF, meshes, etc.) with CORS headers

### WebSocket Data Flow
- **Client sends** (text): JSON with joint control command
  - `{"type": "joint_command", "joint_id": 1, "angle": 1.5}`
- **Server sends** (binary): `0x01` header + JPEG bytes
- **Server sends** (text): JSON with joint telemetry from MuJoCo
  - `{"timestamp": 1234567890.123, "joints": [{"id": 1, "name": "joint_1", "angle": 1.234, "velocity": 0.567, "torque": 0.123}, ...]}`
1. **Server sends** binary data: `0x01` header + JPEG bytes
2. **Server sends** text data: JSON with joint telemetry
3. **Client receives** using `socket.onmessage` with type checking

### 3D Robot Visualization
- Use URDFLoader for robot models
- Raycasting for part selection
- Custom helpers for joint axes and rotation visualization
- Disable OrbitControls during joint dragging
- Robot model is updated from MuJoCo state, not modified directly
- Joint dragging sends commands to backend, which updates MuJoCo and reflects back to frontend

### State Management
- Pinia stores for global state (see stores/counter.ts example)
- Component-level refs for local state
- Real-time data with WebSocket callbacks

## Working on This Project

### Before Making Changes
1. Understand the WebSocket message format
2. Check existing component patterns
3. Run type-check and lint before committing
4. Test with both backend and frontend running

### Common Tasks
- **Adding new telemetry**: Update server joint_data structure and client handlers
- **3D interactions**: RobotViewport.vue has interaction patterns to follow
- **UI components**: Check existing components for styling patterns
- **Performance optimization**: Consider frame rate (30 FPS target) and WebSocket efficiency

## Dependencies

### Backend
- aiohttp >= 3.13.2
- opencv-python >= 4.12.0.88
- mujoco >= 3.0.0

### Frontend
- vue ^3.5.25
- three ^0.182.0
- urdf-loader ^0.12.6
- pinia ^3.0.4
- tailwindcss ^3.4.17
- vitest for testing
- playwright for E2E tests

## Notes

- Video path in server: `test_30fps.mp4` (can be changed to `0` for webcam)
- Target FPS: 30
- WebSocket URL: `ws://localhost:8080/ws`
- URDF endpoint: `GET /urdf` - Returns JSON: `{"url": "http://localhost:8080/assets/xpkg_urdf_archer_l6y/xpkg_urdf_archer_l6y.urdf"}`
- Joint command endpoint: `POST /api/joint/set` - Sets target joint angle
- Static assets served from `soda_server/public/` at `/assets/*`
- CORS is enabled for all endpoints
- MuJoCo uses position control (direct qpos setting)
- Gravity and collision detection are enabled in MuJoCo
