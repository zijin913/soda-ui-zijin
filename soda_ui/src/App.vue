<template>
  <div class="app-root">
    <div class="dashboard-container">
      
      <!-- 1. Top Navigation -->
      <TopBar v-model="currentMouseTool" @toggleDepth="showPointCloud = $event" @toggleRecord="handleRecordToggle" @modeChanged="handleModeChange" />

      <!-- 2. Main Viewport -->
      <main class="main-viewport">
        <!-- 3D Component -->
          <RobotViewport :pointCloudData="pointCloudData" :showPointCloud="showPointCloud" :mode="currentMode" />

        <!-- Floating Camera Panel -->
        <CameraPanel :imageUrl="cameraRgbUrl" />

        <!-- Right Sidebar (Data & Controls) -->
        <RightSidebar :historyData="chartDataHistory" :jointNames="jointNames" :gripperDistance="gripperDistance" />
      </main>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import * as msgpack from '@msgpack/msgpack';
import TopBar from './components/TopBar.vue';
import CameraPanel from './components/CameraPanel.vue';
import RightSidebar from './components/RightSidebar.vue';
import RobotViewport from './components/RobotViewport.vue';

// State
const currentMouseTool = ref('hand');
const currentMode = ref('realtime');
const cameraRgbUrl = ref(null);
const pointCloudData = ref(null);
const showPointCloud = ref(true);
const MAX_HISTORY = 500;
const jointNames = ref({});
const chartDataHistory = ref({});
const gripperDistance = ref(0);

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
    const data = event.data;
    if (data instanceof ArrayBuffer) {
      handleMessagepackData(data);
    }
  };
};

const handleMessagepackData = (arrayBuffer) => {
  const view = new DataView(arrayBuffer);
  const length = view.getUint32(0, true);
  const packedData = new Uint8Array(arrayBuffer, 4, length);

  try {
    const data = msgpack.decode(packedData);

    // Handle video frame
    if (data.video) {
      const blob = new Blob([data.video], { type: 'image/jpeg' });
      const newUrl = URL.createObjectURL(blob);
      if (cameraRgbUrl.value) URL.revokeObjectURL(cameraRgbUrl.value);
      cameraRgbUrl.value = newUrl;
    }

    // Handle point cloud
    if (data.pointcloud && Array.isArray(data.pointcloud) && data.pointcloud.length > 0) {
      const points = data.pointcloud;
      pointCloudData.value = { points };
      window.dispatchEvent(new CustomEvent('point-cloud-update', { detail: { points } }));
    }

    // Handle joints
    if (data.joints && Array.isArray(data.joints)) {
      data.joints.forEach(joint => {
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

      window.dispatchEvent(new CustomEvent('mujoco-joint-states', { detail: data.joints }));
    }

    // Handle gripper distance
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
  console.log('Mode changed to:', newMode);
};

onMounted(() => {
  initWebSocket();
});

onUnmounted(() => {
  if (socket) socket.close();
  if (cameraRgbUrl.value) URL.revokeObjectURL(cameraRgbUrl.value);
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

  /* 
     background-image 可以接受多个值，用逗号分隔。
     第一层：中心向四周变黑的渐变（暗角效果）。
     第二层：点阵图案。
  */
  background-image: radial-gradient(#444 1.5px, transparent 1.5px);
  
  /* 3. 控制间距：由 background-size 决定点与点之间的距离 */
  /* 这里设置为 24px * 24px 的方格重复 */
  background-size: 24px 24px;

  /* 其他布局代码... */
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