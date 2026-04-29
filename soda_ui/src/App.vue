<template>
  <div class="app-root">
    <div class="dashboard-container">
      
      <!-- 1. Top Navigation -->
      <TopBar 
        v-model="currentMouseTool" 
        @toggleDepth="showPointCloud = $event" 
        @toggleRecord="handleRecordToggle" 
        @modeChanged="handleModeChange"
        @recordingLoaded="fetchTrajectory" 
      />

      <!-- 2. Main Viewport -->
      <main class="main-viewport">
        <!-- 3D Component -->
          <RobotViewport
            :pointCloudData="pointCloudData"
            :showPointCloud="showPointCloud"
            :mode="currentMode"
            :dualMode="dualMode"
            @joint-limits-loaded="handleJointLimits"
          />

        <!-- Floating Camera Panel(s) -->
        <template v-if="dualMode">
          <CameraPanel :imageUrl="cameraRgbUrls.left" label="Left Camera" position="top" />
          <CameraPanel :imageUrl="cameraRgbUrls.right" label="Right Camera" position="bottom" />
          <CameraPanel :imageUrl="cameraRgbUrls.side" label="Side Camera" position="lower" />
        </template>
        <CameraPanel v-else :imageUrl="cameraRgbUrl" />

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

      <!-- 3. Progress Bar (Replay mode only) -->
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

    </div>
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

// State
const currentMouseTool = ref('hand');
const currentMode = ref('realtime');
const cameraRgbUrl = ref(null);
const pointCloudData = ref(null);
const showPointCloud = ref(true);
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

// WebSocket Logic
let socket = null;

const initWebSocket = () => {
  const wsUrl = 'ws://localhost:8080/ws';
  socket = new WebSocket(wsUrl);
  socket.binaryType = 'arraybuffer';

  window.socket = socket;

  socket.onopen = () => console.log('WS Connected');

  const sendGripperSet = (distanceMm, side = null) => {
    const distanceMeters = distanceMm / 1000;
    if (socket && socket.readyState === WebSocket.OPEN) {
      const msg = { type: 'gripper_set', distance: distanceMeters };
      if (side) msg.side = side;
      socket.send(JSON.stringify(msg));
    }
  };

  window.sendGripperSet = sendGripperSet;

  socket.onmessage = (event) => {
    if (currentMode.value === 'replay') return;
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
      for (const [side, armData] of Object.entries(data.arms)) {
        // Video per arm
        if (armData.video) {
          const blob = new Blob([armData.video], { type: 'image/jpeg' });
          const newUrl = URL.createObjectURL(blob);
          if (cameraRgbUrls.value[side]) URL.revokeObjectURL(cameraRgbUrls.value[side]);
          cameraRgbUrls.value[side] = newUrl;
        }
        // Joints per arm — keyed by side in chartDataHistory; 3D viewport gets `side` via updateJoints
        if (armData.joints && Array.isArray(armData.joints)) {
          updateJoints(armData.joints, side);
        }
        // Gripper distance per arm
        if (typeof armData.gripper_distance === 'number') {
          gripperDistances.value[side] = armData.gripper_distance * 1000;
        }
      }
      // Side camera (sent separately, not per-arm)
      if (data.side_video) {
        const blob = new Blob([data.side_video], { type: 'image/jpeg' });
        const newUrl = URL.createObjectURL(blob);
        if (cameraRgbUrls.value.side) URL.revokeObjectURL(cameraRgbUrls.value.side);
        cameraRgbUrls.value.side = newUrl;
      }
      // Point cloud (top-level, sent at ~5Hz from left arm's wrist camera in left base frame)
      if (data.pointcloud && Array.isArray(data.pointcloud) && data.pointcloud.length > 0) {
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

const handleRecordToggle = (isRecording) => {
  console.log('Recording:', isRecording ? 'started' : 'stopped');
};

const handleModeChange = (newMode) => {
  currentMode.value = newMode;
  if (newMode === 'replay') {
    fetchTrajectory();
  } else {
    stopPlayback();
  }
};

const fetchTrajectory = async () => {
  try {
    const response = await fetch('http://localhost:8080/api/replay/trajectory');
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
    const response = await fetch(`http://localhost:8080/api/replay/chunk?start_idx=${startIdx}&length=${length}`);
    if (response.ok) {
      const arrayBuffer = await response.arrayBuffer();
      const chunkData = msgpack.decode(new Uint8Array(arrayBuffer));
      
      if (Array.isArray(chunkData)) {
        chunkData.forEach(frame => {
          frameBuffer.value.set(frame.index, {
            video: frame.video, // Uint8Array (bytes)
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

  // 2. Heavy Data (Video/PC) from Buffer
  const heavyFrame = frameBuffer.value.get(frameIdx);
  if (heavyFrame) {
    // Video
    if (heavyFrame.video) {
      // Create blob from bytes
      const blob = new Blob([heavyFrame.video], { type: 'image/jpeg' });
      const src = URL.createObjectURL(blob);
      if (cameraRgbUrl.value && cameraRgbUrl.value.startsWith('blob:')) {
        URL.revokeObjectURL(cameraRgbUrl.value);
      }
      cameraRgbUrl.value = src;
    } else {
      // Optional: clear video if frame has none, or keep last
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

const startPlayback = () => {
  if (playbackInterval) return;
  
  // If we are at the end, restart from 0
  if (replayCurrentFrame.value >= replayTotalFrames.value - 1) {
    replayCurrentFrame.value = 0;
    updateFrameFromLocal(0);
  }

  isPlaying.value = true;
  playbackInterval = setInterval(() => {
    const nextFrame = replayCurrentFrame.value + 1;
    if (nextFrame >= replayTotalFrames.value) {
      stopPlayback(); // Stop at end
      return;
    }
    replayCurrentFrame.value = nextFrame;
    updateFrameFromLocal(nextFrame);
    ensureDataBuffered(nextFrame);
  }, 1000 / TARGET_FPS);
};

const stopPlayback = () => {
  if (playbackInterval) {
    clearInterval(playbackInterval);
    playbackInterval = null;
  }
  isPlaying.value = false;
};

const handleReplayControl = (action) => {
  if (!localTrajectory.value) return;

  if (action === 'play') {
    startPlayback();
  } else if (action === 'pause') {
    stopPlayback();
  } else if (action === 'step_forward') {
    stopPlayback();
    let next = replayCurrentFrame.value + 1;
    if (next >= replayTotalFrames.value) next = replayTotalFrames.value - 1;
    replayCurrentFrame.value = next;
    updateFrameFromLocal(next);
    ensureDataBuffered(next);
  } else if (action === 'step_backward') {
    stopPlayback();
    let prev = replayCurrentFrame.value - 1;
    if (prev < 0) prev = 0;
    replayCurrentFrame.value = prev;
    updateFrameFromLocal(prev);
    // Backward seeking might require fetching previous chunks if we only buffer forward
    // For simplicity, we assume user plays forward mainly. 
    // If we want random access, seek logic handles it.
  }
};

const handleSeek = (frameIdx) => {
  stopPlayback();
  replayCurrentFrame.value = frameIdx;
  
  // Check if frame is buffered
  if (!frameBuffer.value.has(frameIdx)) {
    // If not buffered, force fetch chunk around this frame
    // We fetch starting from frameIdx
    loadedUpToFrame.value = frameIdx; // Reset head
    fetchChunk(frameIdx, CHUNK_SIZE);
  }
  
  updateFrameFromLocal(frameIdx);
};

onMounted(async () => {
  // Detect dual-arm mode from backend
  try {
    const resp = await fetch('http://localhost:8080/system/info');
    if (resp.ok) {
      const info = await resp.json();
      dualMode.value = info.dual_mode || false;
      console.log('System info:', info);
    }
  } catch (e) {
    console.warn('Failed to fetch system info:', e);
  }

  initWebSocket();
  if (currentMode.value === 'replay') {
    fetchTrajectory();
  }
});

onUnmounted(() => {
  stopPlayback();
  if (socket) socket.close();
  if (cameraRgbUrl.value && cameraRgbUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(cameraRgbUrl.value);
  }
  pointCloudData.value = null;
});
</script>

<style>
/* Global Layout Styles */
body {
  margin: 0;
  padding: 0;
  overflow: hidden;
  font-family: 'Inter', sans-serif;
}

.app-root {
  width: 100vw;
  height: 100vh;
  background-color: #303130;
  background-image: radial-gradient(#444 1.5px, transparent 1.5px);
  background-size: 24px 24px;
  font-family: 'Inter', sans-serif;
  color: #ffffff;
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
</style>