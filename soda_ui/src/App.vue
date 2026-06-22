<template>
  <div class="app-root">
    <div class="dashboard-container">
      
      <!-- 1. Top Navigation -->
      <TopBar
        @toggleDepth="showPointCloud = $event"
        @toggleCoordinate="showCoordinate = $event"
        @teleopToggled="handleTeleopToggle"
        @modeChanged="handleModeChange"
        @recordingLoaded="fetchTrajectory"
      />

      <!-- 2. Main Viewport -->
      <main class="main-viewport">
        <!-- 3D Component -->
          <RobotViewport
            :pointCloudData="pointCloudData"
            :showPointCloud="showPointCloud"
            :showCoordinate="showCoordinate"
            :mode="currentMode"
            :dualMode="dualMode"
            @joint-limit-loaded="handleJointLimits"
          />

        <!-- Floating Camera Panel(s) -->
        <template v-if="dualMode">
          <CameraPanel :imageUrl="cameraRgbUrls.left" label="Left Camera" position="top" :showCalibrate="currentMode === 'realtime'" />
          <CameraPanel :imageUrl="cameraRgbUrls.right" label="Right Camera" position="bottom" />
          <CameraPanel :imageUrl="cameraRgbUrls.side" label="Side Camera" position="lower" />
        </template>
        <CameraPanel v-else :imageUrl="cameraRgbUrl" :showCalibrate="currentMode === 'realtime'" />

        <!-- Right Sidebar (Data & Controls) -->
        <RightSidebar
          :historyData="chartDataHistory"
          :baselines="chartBaselines"
          :jointNames="jointNames"
          :gripperDistances="gripperDistances"
          :dualMode="dualMode"
          :fullData="fullJointData"
          :mode="currentMode"
          :currentFrame="replayCurrentFrame"
          :totalFrames="replayTotalFrames"
        />

      </main>

      <!-- 3a. Joint clearance strip — disabled per user request.
           Re-enable by uncommenting the block and the import below.
      <JointClearanceRow
        v-if="currentMode === 'realtime' && conn.isOperational"
        :history="chartDataHistory"
        :jointNames="jointNames"
        :jointLimits="jointLimits"
        :dualMode="dualMode"
        class="clearance-strip"
      />
      -->


      <!-- 3b. Progress Bar (Replay mode only) -->
      <TimelineControl
        v-if="currentMode === 'replay'"
        :currentFrame="replayCurrentFrame"
        :totalFrames="replayTotalFrames"
        :isPlaying="isPlaying"
        @play="handleReplayControl('play')"
        @pause="handleReplayControl('pause')"
        @stepForward="handleReplayControl('step_forward')"
        @stepBackward="handleReplayControl('step_backward')"
        @seek="handleSeek"
      />

      <!-- 4. Launcher overlay — shown whenever we're not fully operational
           (launcher down, backend down, or WS disconnected). Collapses to a
           one-line status pill in StatusRail otherwise. -->
      <LauncherCard v-if="!conn.isOperational" />

      <!-- 5. Zero-gravity safety banner — high-visibility warning whenever
           the recovery launcher is running (real-arm hand-pose mode). Stays
           visible as a slim header reminder even after the modal is dismissed. -->
      <ZeroGravityBanner />

      <!-- 5b. Teleop banner — same pattern as zero-g: shows when the teleop
           overlay was dismissed but teleop is still active. Click to re-open. -->
      <TeleopBanner />

      <!-- 5c. Calibration banner — shows when the calibration panel was
           dismissed but a session is still open. Click to re-open the panel. -->
      <CalibrationBanner />

      <!-- 5d. Host-policy banner — shows when the policy panel was dismissed
           but a rollout is still running. Click to re-open the panel. -->
      <HostPolicyBanner />

      <!-- 5e. Teach/programming banner — shown while both arms are floated for
           hand-guiding. Reminder + quick EXIT (hold pose). -->
      <TeachModeBanner />

    </div>

    <!-- 6. Zero-gravity recovery overlay — fullscreen phosphor modal shown
         whenever conn.zeroGravityActive flips true. Replaces the OpenCV
         popup that recover_zerog.py used to host on the robot desktop. -->
    <RecoveryModal />

    <!-- 7. Stop confirmation (phosphor in-UI replacement for window.confirm).
         Lives at root so it stacks above LauncherCard regardless of where the
         caller (TopBar / LauncherCard) is mounted. -->
    <StopConfirmModal
      :open="conn.stopConfirmOpen"
      :is-real="conn.mode === 'real'"
      @confirm="conn.confirmStop"
      @cancel="conn.closeStopConfirm"
    />

    <!-- 7b. Teach-mode confirm — real-mode guard before floating both arms. -->
    <TeachConfirmModal />

    <!-- 9. Teleop overlay — fullscreen phosphor modal shown while teleop is
         running. Replaces the OpenCV viewer popup; reuses our existing
         per-camera blob URLs (no new camera connection on the backend). -->
    <TeleopOverlay :cameras="cameraRgbUrls" />

    <!-- 9b. Camera calibration modal — phosphor panel with annotated ChArUco
         stream; opened from the TopBar CALIB button. Runs through the backend's
         single command client (no teleop conflict). -->
    <CalibrationModal />

    <!-- 9c. Host-policy modal — pick a policy + params and run it through the
         shared services (probe / dry-run / live). Opened from the POLICY button. -->
    <HostPolicyModal />

    <!-- 10. Persistent log panel — floats bottom-right, color-coded backend
         and hw streams. Stays visible after LauncherCard dismisses so the
         user can keep an eye on the streams during normal operation. -->
    <LogPanel />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue';
import * as msgpack from '@msgpack/msgpack';
import TopBar from './components/TopBar.vue';
import CameraPanel from './components/CameraPanel.vue';
import RightSidebar from './components/RightSidebar.vue';
import RobotViewport from './components/RobotViewport.vue';
import TimelineControl from './components/TimelineControl.vue';
import LauncherCard from './components/LauncherCard.vue';
import ZeroGravityBanner from './components/ZeroGravityBanner.vue';
import RecoveryModal from './components/RecoveryModal.vue';
import StopConfirmModal from './components/StopConfirmModal.vue';
import LogPanel from './components/LogPanel.vue';
import TeleopOverlay from './components/TeleopOverlay.vue';
import TeleopBanner from './components/TeleopBanner.vue';
import CalibrationModal from './components/CalibrationModal.vue';
import CalibrationBanner from './components/CalibrationBanner.vue';
import HostPolicyModal from './components/HostPolicyModal.vue';
import HostPolicyBanner from './components/HostPolicyBanner.vue';
import TeachModeBanner from './components/TeachModeBanner.vue';
import TeachConfirmModal from './components/TeachConfirmModal.vue';
// import JointClearanceRow from './components/JointClearanceRow.vue';  // disabled per user
import { useConnectionStore } from '@/stores/connection';

// Tiered connection state (launcher / backend / hw / WS). The launcher is
// our anchor — once it's reachable we know whether the backend is up, and
// only then do we try to open the WebSocket.
const conn = useConnectionStore();

// State
const currentMode = ref('realtime');
const cameraRgbUrl = ref(null);
const pointCloudData = ref(null);
const showPointCloud = ref(true);
const showCoordinate = ref(false);
const MAX_HISTORY = 500;
const jointNames = ref({});
const chartDataHistory = ref({ left: {}, right: {} });
// First angle observed per (side, id). Used as the chart's zero so we plot
// deviation from rest instead of absolute joint angle (otherwise a joint
// resting at e.g. -1.5 rad sits outside the ±1.0 view window).
const chartBaselines = ref({ left: {}, right: {} });
const jointLimits = ref({});
const gripperDistances = ref({ left: 0, right: 0 });

// Dual-arm state
const dualMode = ref(false);
const cameraRgbUrls = ref({ left: null, right: null, side: null });

// Replay state
const replayCurrentFrame = ref(0);
const replayTotalFrames = ref(0);
const isPlaying = ref(false);
const localTrajectory = ref(null); // Lightweight: joints + timestamp only
const frameBuffer = ref(new Map()); // Heavy: index -> { video, pointcloud }
const isLoadingChunk = ref(false);
const loadedUpToFrame = ref(0);

let playbackInterval = null;
const TARGET_FPS = 30;
const CHUNK_SIZE = 300; // 10 seconds @ 30fps

const fullJointData = computed(() => {
  if (!localTrajectory.value || localTrajectory.value.length === 0) return {};
  const data = {};
  
  localTrajectory.value.forEach(frame => {
    frame.joints.forEach((j, idx) => {
      // Use index as ID if name mapping isn't set up yet, or strictly use index
      const id = idx;
      if (!data[id]) {
        data[id] = { angle: [], velocity: [], torque: [] };
        // Populate jointNames if missing
        if (!jointNames.value[id]) jointNames.value[id] = j.name;
      }
      data[id].angle.push(j.angle);
      data[id].velocity.push(j.velocity);
      data[id].torque.push(j.torque);
    });
  });
  return data;
});

// Split backend's [[x,y,z,r,g,b], ...] into separate points/colors arrays for the viewport.
// Falls back to no colors if rows are length 3 (legacy/uncolored clouds).
// Decode the backend's binary point cloud (Uint8Array of float32
// x,y,z,r,g,b per point) into { points: [[x,y,z]...], colors: [[r,g,b]...] }.
// We copy via slice() so the Float32Array view is 4-byte aligned regardless
// of the msgpack buffer's offset.
const decodePcBin = (pcBin, n) => {
  try {
    const u8 = pcBin instanceof Uint8Array ? pcBin : new Uint8Array(pcBin);
    const f32 = new Float32Array(u8.slice().buffer);
    if (f32.length < n * 6) return null;
    const points = new Array(n);
    const colors = new Array(n);
    for (let i = 0; i < n; i++) {
      const o = i * 6;
      points[i] = [f32[o], f32[o + 1], f32[o + 2]];
      colors[i] = [f32[o + 3], f32[o + 4], f32[o + 5]];
    }
    return { points, colors };
  } catch (e) {
    console.error('decodePcBin failed:', e);
    return null;
  }
};

const splitXyzRgb = (raw) => {
  const first = raw[0];
  if (!Array.isArray(first) || first.length < 6) {
    return { points: raw };
  }
  const n = raw.length;
  const points = new Array(n);
  const colors = new Array(n);
  for (let i = 0; i < n; i++) {
    const r = raw[i];
    points[i] = [r[0], r[1], r[2]];
    colors[i] = [r[3], r[4], r[5]];
  }
  return { points, colors };
};

// WebSocket Logic — reconnects with exponential backoff (1s → 30s) and only
// attempts to connect once the launcher reports backend === 'up'. On close,
// clears stale camera blobs so the page makes it visually obvious the live
// stream is gone (instead of freezing on the last frame).
let socket = null;
let reconnectDelay = 1000;
let reconnectTimer = null;

const clearStaleCameras = () => {
  if (cameraRgbUrl.value && cameraRgbUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(cameraRgbUrl.value);
  }
  cameraRgbUrl.value = null;
  // MJPEG URLs (http://…/camera/stream?cam=X) live independently of the
  // legacy /ws and are reset only when backend transitions through 'down'.
  // Only revoke leftover blob: URLs from older protocol versions.
  for (const k of ['left', 'right', 'side']) {
    const u = cameraRgbUrls.value[k];
    if (u && u.startsWith('blob:')) URL.revokeObjectURL(u);
  }
};

// Build MJPEG URLs for the three cameras. Each <img> opens its own HTTP
// streaming connection, so backpressure on any one cam (or on the state WS)
// can't starve the others. Cache-bust suffix forces a fresh connection if
// the backend was restarted (otherwise the browser may reuse the dead one).
const mjpegUrl = (cam) => {
  const base = conn.backendUrl;
  if (!base) return null;
  return `${base}/camera/stream?cam=${cam}&_=${Date.now()}`;
};
const wireMjpegCameras = () => {
  cameraRgbUrls.value = {
    left:  mjpegUrl('left'),
    right: mjpegUrl('right'),
    side:  mjpegUrl('side'),
  };
};
const tearDownMjpegCameras = () => {
  // Setting src to null aborts the in-flight MJPEG GET on the browser side.
  cameraRgbUrls.value = { left: null, right: null, side: null };
};

// Hoisted out of initWebSocket so reconnects don't redefine the global.
window.sendGripperSet = (distanceMm, side = null) => {
  const distanceMeters = distanceMm / 1000;
  if (socket && socket.readyState === WebSocket.OPEN) {
    const msg = { type: 'gripper_set', distance: distanceMeters };
    if (side) msg.side = side;
    socket.send(JSON.stringify(msg));
  }
};

const initWebSocket = () => {
  if (socket && (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN)) {
    return;
  }
  if (conn.backend !== 'up') {
    // Backend isn't ready yet — try again soon. The watcher below also kicks
    // in immediately when conn.backend flips to 'up'.
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(initWebSocket, 1000);
    return;
  }
  socket = new WebSocket(conn.wsUrl);
  socket.binaryType = 'arraybuffer';
  window.socket = socket;

  socket.onopen = () => {
    conn.setWsConnected(true);
    reconnectDelay = 1000;
    console.log('WS Connected to', conn.wsUrl);
  };
  socket.onclose = () => {
    conn.setWsConnected(false);
    clearStaleCameras();
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(initWebSocket, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  };
  socket.onerror = () => {
    try { socket && socket.close(); } catch { /* ignore */ }
  };
  socket.onmessage = (event) => {
    conn.tickWsFrame();
    // Render live state in BOTH modes — during replay the backend physically
    // moves the arm, so the live /ws stream carries the replay motion.
    const data = event.data;
    if (data instanceof ArrayBuffer) {
      handleMessagepackData(data);
    }
  };
};

const handleJointLimits = (limits) => {
  jointLimits.value = limits;
};

const updateJoints = (joints, side = 'left') => {
  if (!chartDataHistory.value[side]) chartDataHistory.value[side] = {};
  if (!chartBaselines.value[side]) chartBaselines.value[side] = {};
  const bucket = chartDataHistory.value[side];
  const baselines = chartBaselines.value[side];
  joints.forEach(joint => {
    const id = joint.id;
    if (joint.name) {
      jointNames.value[id] = joint.name;
    }
    if (!bucket[id]) {
      bucket[id] = { angle: [], velocity: [], torque: [] };
      baselines[id] = joint.angle || 0;
    }
    bucket[id].angle.push(joint.angle || 0);
    bucket[id].velocity.push(joint.velocity || 0);
    bucket[id].torque.push(joint.torque || 0);

    if (bucket[id].angle.length > MAX_HISTORY) bucket[id].angle.shift();
    if (bucket[id].velocity.length > MAX_HISTORY) bucket[id].velocity.shift();
    if (bucket[id].torque.length > MAX_HISTORY) bucket[id].torque.shift();
  });

  // 3D viewport keys joints by `side` field; preserve any existing one, fall back to the arg
  const detail = joints.map(j => ({ ...j, side: j.side ?? side }));
  window.dispatchEvent(new CustomEvent('mujoco-joint-states', { detail }));
};

const handleMessagepackData = (arrayBuffer) => {
  const view = new DataView(arrayBuffer);
  const length = view.getUint32(0, true);
  const packedData = new Uint8Array(arrayBuffer, 4, length);

  try {
    const data = msgpack.decode(packedData);

    if (data.dual_mode && data.arms) {
      // ── Dual-arm protocol ──
      // Camera video is consumed via the dedicated MJPEG endpoints
      // (cameraRgbUrls is wired up by the backend-up watcher below) — we
      // intentionally ignore data.video / data.side_video here so the legacy
      // /ws message stays small (state + cloud only) and never starves the
      // 3D viewport when bandwidth gets tight.
      for (const [side, armData] of Object.entries(data.arms)) {
        // Joints per arm — keyed by side in chartDataHistory; 3D viewport gets `side` via updateJoints
        if (armData.joints && Array.isArray(armData.joints)) {
          updateJoints(armData.joints, side);
        }
        // Gripper distance per arm
        if (typeof armData.gripper_distance === 'number') {
          gripperDistances.value[side] = armData.gripper_distance * 1000;
        }
      }
      // Point cloud — binary float32 (x,y,z,r,g,b per point), sent once per
      // new cloud from the backend's background worker. Decoded into the same
      // { points, colors } shape splitXyzRgb produces, so the viewport is
      // unchanged. (Legacy list form `data.pointcloud` still handled below.)
      if (data.pc_bin && data.pc_n > 0) {
        const detail = decodePcBin(data.pc_bin, data.pc_n);
        if (detail) {
          pointCloudData.value = detail;
          window.dispatchEvent(new CustomEvent('point-cloud-update', { detail }));
        }
      } else if (data.pointcloud && Array.isArray(data.pointcloud) && data.pointcloud.length > 0) {
        const detail = splitXyzRgb(data.pointcloud);
        pointCloudData.value = detail;
        window.dispatchEvent(new CustomEvent('point-cloud-update', { detail }));
      }
    } else {
      // ── Single-arm protocol (unchanged) ──
      if (data.video) {
        const blob = new Blob([data.video], { type: 'image/jpeg' });
        const newUrl = URL.createObjectURL(blob);
        if (cameraRgbUrl.value) URL.revokeObjectURL(cameraRgbUrl.value);
        cameraRgbUrl.value = newUrl;
      }
      if (data.pointcloud && Array.isArray(data.pointcloud) && data.pointcloud.length > 0) {
        const detail = splitXyzRgb(data.pointcloud);
        pointCloudData.value = detail;
        window.dispatchEvent(new CustomEvent('point-cloud-update', { detail }));
      }
      if (data.joints && Array.isArray(data.joints)) {
        updateJoints(data.joints);
      }
      if (typeof data.gripper_distance === 'number') {
        gripperDistances.value.left = data.gripper_distance * 1000;
      }
    }
  } catch (e) {
    console.error('Failed to decode MessagePack:', e);
  }
};

const handleTeleopToggle = (isRunning) => {
  console.log('Teleop:', isRunning ? 'started' : 'stopped');
};

const handleModeChange = (newMode) => {
  currentMode.value = newMode;
  if (newMode === 'replay') {
    fetchTrajectory();
  } else {
    stopStatusPolling();
  }
};

const fetchTrajectory = async () => {
  try {
    // Skip until a recording is actually loaded — avoids a 400 on a bare
    // mode-switch to replay before an episode is selected. /api/replay/status
    // returns {is_loaded:false} with a clean 200, so nothing is logged.
    const st = await fetch(`${conn.backendUrl}/api/replay/status`);
    if (st.ok && !(await st.json()).is_loaded) return;

    const response = await fetch(`${conn.backendUrl}/api/replay/trajectory`);
    if (response.ok) {
      const data = await response.json();
      localTrajectory.value = data.trajectory || [];
      replayTotalFrames.value = localTrajectory.value.length;
      
      // Reset buffer and load first chunk
      frameBuffer.value.clear();
      loadedUpToFrame.value = 0;
      await fetchChunk(0, CHUNK_SIZE);

      replayCurrentFrame.value = 0;
      updateFrameFromLocal(0);
      console.log('Trajectory metadata loaded:', localTrajectory.value.length, 'frames');
    }
  } catch (error) {
    console.error('Failed to fetch trajectory:', error);
  }
};

const fetchChunk = async (startIdx, length) => {
  if (isLoadingChunk.value) return;
  isLoadingChunk.value = true;
  
  try {
    console.log(`Fetching chunk: ${startIdx} to ${startIdx + length}`);
    const response = await fetch(`${conn.backendUrl}/api/replay/chunk?start_idx=${startIdx}&length=${length}`);
    if (response.ok) {
      const arrayBuffer = await response.arrayBuffer();
      const chunkData = msgpack.decode(new Uint8Array(arrayBuffer));
      
      if (Array.isArray(chunkData)) {
        chunkData.forEach(frame => {
          frameBuffer.value.set(frame.index, {
            // `videos` is the new per-camera map produced by the
            // dual-arm ReplayManager ({left_wrist, right_wrist, side}).
            // `video` is kept for backwards compat with older
            // single-camera recordings.
            videos: frame.videos || null,
            video: frame.video,
            pointcloud: frame.pointcloud
          });
        });
        
        // Update marker
        const chunkEnd = startIdx + chunkData.length;
        if (chunkEnd > loadedUpToFrame.value) {
          loadedUpToFrame.value = chunkEnd;
        }
      }
    }
  } catch (error) {
    console.error('Failed to fetch chunk:', error);
  } finally {
    isLoadingChunk.value = false;
  }
};

const ensureDataBuffered = (currentFrame) => {
  if (isLoadingChunk.value) return;
  if (currentFrame >= replayTotalFrames.value - 1) return;

  // Check how many frames ahead we have
  const bufferRemaining = loadedUpToFrame.value - currentFrame;
  const fiveSecondsFrames = 5 * TARGET_FPS;

  // If less than 5s remaining in buffer, and we haven't loaded everything
  if (bufferRemaining < fiveSecondsFrames && loadedUpToFrame.value < replayTotalFrames.value) {
    const nextStart = loadedUpToFrame.value;
    // Fetch next 10s
    fetchChunk(nextStart, CHUNK_SIZE);
  }
};

const updateFrameFromLocal = (frameIdx) => {
  if (!localTrajectory.value || !localTrajectory.value[frameIdx]) return;
  
  // 1. Joints (Lightweight, always available)
  const metaFrame = localTrajectory.value[frameIdx];
  const nameToId = {};
  for (const [id, name] of Object.entries(jointNames.value)) {
    nameToId[name] = parseInt(id);
  }
  const jointsWithId = metaFrame.joints.map(j => ({
    ...j,
    id: nameToId[j.name] !== undefined ? nameToId[j.name] : -1
  }));
  updateJoints(jointsWithId);

  if (typeof metaFrame.gripper_distance === 'number') {
    gripperDistances.value.left = metaFrame.gripper_distance * 1000;
  }
  if (typeof metaFrame.gripper_distance_right === 'number') {
    gripperDistances.value.right = metaFrame.gripper_distance_right * 1000;
  }

  // 2. Heavy Data (Video/PC) from Buffer
  const heavyFrame = frameBuffer.value.get(frameIdx);
  if (heavyFrame) {
    // Per-camera videos (left/right wrist + side). The cam_key →
    // panel key mapping is the same on both ends: "left_wrist" feeds
    // the left CameraPanel, etc.
    const camKeyToPanel = {
      left_wrist: 'left',
      right_wrist: 'right',
      side: 'side',
    };
    if (heavyFrame.videos) {
      for (const [camKey, bytes] of Object.entries(heavyFrame.videos)) {
        const panel = camKeyToPanel[camKey];
        if (!panel || !bytes) continue;
        const blob = new Blob([bytes], { type: 'image/jpeg' });
        const newUrl = URL.createObjectURL(blob);
        const prev = cameraRgbUrls.value[panel];
        if (prev && prev.startsWith('blob:')) URL.revokeObjectURL(prev);
        cameraRgbUrls.value[panel] = newUrl;
      }
    } else if (heavyFrame.video) {
      // Legacy single-camera recording — feed the left panel only.
      const blob = new Blob([heavyFrame.video], { type: 'image/jpeg' });
      const src = URL.createObjectURL(blob);
      const prev = cameraRgbUrls.value.left;
      if (prev && prev.startsWith('blob:')) URL.revokeObjectURL(prev);
      cameraRgbUrls.value.left = src;
      // Keep the old single-camera ref in sync for the non-dual layout.
      if (cameraRgbUrl.value && cameraRgbUrl.value.startsWith('blob:')) {
        URL.revokeObjectURL(cameraRgbUrl.value);
      }
      cameraRgbUrl.value = src;
    }

    // Pointcloud
    if (heavyFrame.pointcloud) {
      const detail = splitXyzRgb(heavyFrame.pointcloud);
      pointCloudData.value = detail;
      window.dispatchEvent(new CustomEvent('point-cloud-update', { detail }));
    }
  } else {
    // Data not loaded yet for this frame
    // Ideally show a loading spinner or keep last frame
    // For now, we just rely on joint updates which are instant
  }
};

// Replay is BACKEND-DRIVEN: a backend task advances frames and commands the
// sim/real arm via set_cmds, so the arm physically moves and the live /ws
// state stream (rendered like realtime) shows it in 3D + cameras. The
// frontend just sends control intents and polls /api/replay/status to keep
// the timeline + play/pause icon in sync. (The old client-side joint
// animation never moved the 3D — recorded joint names didn't match the
// realtime ones — so it's removed.)
const driveBackendReplay = async (action, frame = null) => {
  try {
    await fetch(`${conn.backendUrl}/api/replay/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(frame === null ? { action } : { action, frame }),
    });
  } catch (e) {
    console.error('replay control failed:', action, e);
  }
};

const startStatusPolling = () => {
  if (playbackInterval) clearInterval(playbackInterval);
  playbackInterval = setInterval(async () => {
    try {
      const r = await fetch(`${conn.backendUrl}/api/replay/status`);
      if (!r.ok) return;
      const st = await r.json();
      if (typeof st.current_frame === 'number') replayCurrentFrame.value = st.current_frame;
      if (typeof st.is_playing === 'boolean') isPlaying.value = st.is_playing;
      if (!st.is_playing) stopStatusPolling();
    } catch { /* ignore */ }
  }, 150);
};

const stopStatusPolling = () => {
  if (playbackInterval) {
    clearInterval(playbackInterval);
    playbackInterval = null;
  }
};

const handleReplayControl = (action) => {
  if (replayTotalFrames.value === 0) return;

  if (action === 'play') {
    isPlaying.value = true;
    driveBackendReplay('seek', replayCurrentFrame.value)
      .then(() => driveBackendReplay('play'))
      .then(() => startStatusPolling());
  } else if (action === 'pause') {
    stopStatusPolling();
    isPlaying.value = false;
    driveBackendReplay('pause');
  } else if (action === 'step_forward') {
    stopStatusPolling();
    let next = replayCurrentFrame.value + 1;
    if (next >= replayTotalFrames.value) next = replayTotalFrames.value - 1;
    replayCurrentFrame.value = next;
    driveBackendReplay('seek', next);
  } else if (action === 'step_backward') {
    stopStatusPolling();
    let prev = replayCurrentFrame.value - 1;
    if (prev < 0) prev = 0;
    replayCurrentFrame.value = prev;
    driveBackendReplay('seek', prev);
  }
};

const handleSeek = (frameIdx) => {
  stopStatusPolling();
  isPlaying.value = false;
  replayCurrentFrame.value = frameIdx;
  driveBackendReplay('seek', frameIdx);
};

// Re-attempt WS connection the instant the launcher reports the backend
// is up (avoids waiting a full 1s for the next initWebSocket setTimeout).
// Also wires up the per-camera MJPEG streams here so they come back online
// after the backend restarts (and tears them down on backend === 'down').
watch(() => conn.backend, (newState) => {
  if (newState === 'up') {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      initWebSocket();
    }
    wireMjpegCameras();
  } else if (newState === 'down') {
    tearDownMjpegCameras();
  }
}, { immediate: true });

// Detect dual-arm mode once the backend is reachable, then keep watching in
// case the backend is restarted in a different mode.
const fetchSystemInfo = async () => {
  try {
    const resp = await fetch(`${conn.backendUrl}/system/info`);
    if (resp.ok) {
      const info = await resp.json();
      dualMode.value = info.dual_mode || false;
      console.log('System info:', info);
    }
  } catch (e) {
    console.warn('Failed to fetch system info:', e);
  }
};
watch(() => conn.backend, (s) => { if (s === 'up') fetchSystemInfo(); });

// Open /ws/teleop_ui whenever teleop is running so the TeleopOverlay receives
// live status pushes from the backend TeleopBridge. Close on teleop end.
watch(() => conn.teleopRunning, (running) => {
  if (running) conn.openTeleopWs();
  else conn.closeTeleopWs();
}, { immediate: true });

onMounted(() => {
  conn.startPolling();    // GET /launcher/status every 1s
  initWebSocket();        // no-op until conn.backend === 'up'
  if (currentMode.value === 'replay') {
    fetchTrajectory();
  }
});

onUnmounted(() => {
  conn.stopPolling();
  conn.stopLogTail();
  stopStatusPolling();
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  if (socket) socket.close();
  if (cameraRgbUrl.value && cameraRgbUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(cameraRgbUrl.value);
  }
  for (const key of ['left', 'right', 'side']) {
    const url = cameraRgbUrls.value[key];
    if (url && url.startsWith('blob:')) URL.revokeObjectURL(url);
  }
  pointCloudData.value = null;
});
</script>

<style>
/* Global Layout Styles — phosphor industrial control-room palette. */
body {
  margin: 0;
  padding: 0;
  overflow: hidden;
  font-family: ui-monospace, "SF Mono", "JetBrains Mono",
               "DejaVu Sans Mono", Menlo, Consolas, monospace;
  background: #06080b;
}

.app-root {
  /* Counter the global `html { zoom }` so the dashboard still fills the screen.
     Sized at 1 / zoom (0.8 -> 125vw/125vh) because viewport units are NOT
     rescaled by CSS zoom. Keep these two in sync with the zoom in main.css. */
  width: 125vw;
  height: 125vh;
  background-color: #06080b;
  /* Pi's 34px hairline grid + faint vignette wash. */
  background-image:
    radial-gradient(120% 90% at 50% -10%, rgba(40,60,80,0.10), transparent 60%),
    radial-gradient(140% 120% at 50% 120%, rgba(255,176,32,0.04), transparent 55%),
    linear-gradient(#19212b 1px, transparent 1px),
    linear-gradient(90deg, #19212b 1px, transparent 1px);
  background-size: auto, auto, 34px 34px, 34px 34px;
  background-position: 0 0, 0 0, -1px -1px, -1px -1px;
  font-family: ui-monospace, "SF Mono", "JetBrains Mono",
               "DejaVu Sans Mono", Menlo, Consolas, monospace;
  color: #c6d3e0;
  letter-spacing: 0.2px;
  -webkit-font-smoothing: antialiased;
  overflow: hidden;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  margin: 0;
}

.dashboard-container {
  width: 99%;
  height: 99%;
  position: relative;
  display: flex;
  flex-direction: column;
}

.main-viewport {
  flex: 1;
  position: relative;
  display: flex;
  overflow: hidden;
}

/* Prominent PROGRAMMING / EXECUTION switch, floated at the top-center.
   z-index sits ABOVE the teleop (9500) and policy (10200) modals so it stays
   reachable to barge into a running task while their panel is open. */

/* Joint clearance strip sits between the viewport and the bottom edge
 * (or the TimelineControl in replay mode). Stays out of overlay z-index. */
.clearance-strip {
  margin: 6px 12px 8px;
}
</style>