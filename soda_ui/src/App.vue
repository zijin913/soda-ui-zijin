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
            @joint-limits-loaded="handleJointLimits"
          />

        <!-- Floating Camera Panel -->
        <CameraPanel :imageUrl="cameraRgbUrl" />

        <!-- Right Sidebar (Data & Controls) -->
        <RightSidebar 
          :historyData="chartDataHistory" 
          :jointNames="jointNames" 
          :gripperDistance="gripperDistance" 
          :fullData="fullJointData"
          :mode="currentMode"
          :currentFrame="replayCurrentFrame"
          :totalFrames="replayTotalFrames"
          :jointLimits="jointLimits"
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
const chartDataHistory = ref({});
const jointLimits = ref({});
const gripperDistance = ref(0);

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

// WebSocket Logic
let socket = null;

const initWebSocket = () => {
  const wsUrl = 'ws://localhost:8080/ws';
  socket = new WebSocket(wsUrl);
  socket.binaryType = 'arraybuffer';

  window.socket = socket;

  socket.onopen = () => console.log('WS Connected');

  const sendGripperSet = (distanceMm) => {
    const distanceMeters = distanceMm / 1000;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({
        type: 'gripper_set',
        distance: distanceMeters
      }));
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

const updateJoints = (joints) => {
  joints.forEach(joint => {
    const id = joint.id;
    if (joint.name) {
      jointNames.value[id] = joint.name;
    }
    if (!chartDataHistory.value[id]) {
      chartDataHistory.value[id] = { angle: [], velocity: [], torque: [] };
    }
    chartDataHistory.value[id].angle.push(joint.angle || 0);
    chartDataHistory.value[id].velocity.push(joint.velocity || 0);
    chartDataHistory.value[id].torque.push(joint.torque || 0);

    if (chartDataHistory.value[id].angle.length > MAX_HISTORY) chartDataHistory.value[id].angle.shift();
    if (chartDataHistory.value[id].velocity.length > MAX_HISTORY) chartDataHistory.value[id].velocity.shift();
    if (chartDataHistory.value[id].torque.length > MAX_HISTORY) chartDataHistory.value[id].torque.shift();
  });

  window.dispatchEvent(new CustomEvent('mujoco-joint-states', { detail: joints }));
};

const handleMessagepackData = (arrayBuffer) => {
  const view = new DataView(arrayBuffer);
  const length = view.getUint32(0, true);
  const packedData = new Uint8Array(arrayBuffer, 4, length);

  try {
    const data = msgpack.decode(packedData);
    if (data.video) {
      const blob = new Blob([data.video], { type: 'image/jpeg' });
      const newUrl = URL.createObjectURL(blob);
      if (cameraRgbUrl.value) URL.revokeObjectURL(cameraRgbUrl.value);
      cameraRgbUrl.value = newUrl;
    }
    if (data.pointcloud && Array.isArray(data.pointcloud) && data.pointcloud.length > 0) {
      const points = data.pointcloud;
      pointCloudData.value = { points };
      window.dispatchEvent(new CustomEvent('point-cloud-update', { detail: { points } }));
    }
    if (data.joints && Array.isArray(data.joints)) {
      updateJoints(data.joints);
    }
    if (typeof data.gripper_distance === 'number') {
      gripperDistance.value = data.gripper_distance * 1000;
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
    gripperDistance.value = metaFrame.gripper_distance * 1000;
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
      const points = heavyFrame.pointcloud;
      pointCloudData.value = { points };
      window.dispatchEvent(new CustomEvent('point-cloud-update', { detail: { points } }));
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

onMounted(() => {
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