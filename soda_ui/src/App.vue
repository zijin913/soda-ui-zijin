<template>
  <div class="app-root">
    <div class="dashboard-container">
      
      <!-- 1. Top Navigation -->
      <TopBar v-model="currentMouseTool" @toggleDepth="showPointCloud = $event" @toggleRecord="handleRecordToggle" />

      <!-- 2. Main Viewport -->
      <main class="main-viewport">
        <!-- 3D Component -->
        <RobotViewport :pointCloudData="pointCloudData" :showPointCloud="showPointCloud" />

        <!-- Floating Camera Panel -->
        <CameraPanel :imageUrl="cameraRgbUrl" />

        <!-- Right Sidebar (Data & Controls) -->
        <RightSidebar :historyData="chartDataHistory" :jointNames="jointNames" />
      </main>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import TopBar from './components/TopBar.vue';
import CameraPanel from './components/CameraPanel.vue';
import RightSidebar from './components/RightSidebar.vue';
import RobotViewport from './components/RobotViewport.vue';

// State
const currentMouseTool = ref('hand');
const cameraRgbUrl = ref(null);
const pointCloudData = ref(null);
const showPointCloud = ref(true);
const MAX_HISTORY = 500;
const jointNames = ref({});
const chartDataHistory = ref({});

// WebSocket Logic
let socket = null;

const initWebSocket = () => {
  const wsUrl = 'ws://localhost:8080/ws';
  socket = new WebSocket(wsUrl);
  socket.binaryType = 'arraybuffer';
  
  window.socket = socket;

  socket.onopen = () => console.log('WS Connected');

  socket.onmessage = (event) => {
    const data = event.data;
    if (typeof data === 'string') {
      try {
        const telemetry = JSON.parse(data);
        handleTelemetry(telemetry);
      } catch (e) { console.error(e); }
    } else if (data instanceof ArrayBuffer) {
      handleBinaryData(data);
    }
  };
};

const handleTelemetry = (data) => {
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
};

const handleBinaryData = (arrayBuffer) => {
  const view = new DataView(arrayBuffer);
  const header = view.getUint8(0);
  if (header === 0x01) {
    const imageBytes = arrayBuffer.slice(1);
    const blob = new Blob([imageBytes], { type: 'image/jpeg' });
    const newUrl = URL.createObjectURL(blob);
    if (cameraRgbUrl.value) URL.revokeObjectURL(cameraRgbUrl.value);
    cameraRgbUrl.value = newUrl;
  } else if (header === 0x02) {
    const pcBytes = arrayBuffer.slice(1);
    const float32Array = new Float32Array(pcBytes);
    const points = [];
    for (let i = 0; i < float32Array.length; i += 3) {
      points.push([float32Array[i], float32Array[i + 1], float32Array[i + 2]]);
    }
    pointCloudData.value = points;
    window.dispatchEvent(new CustomEvent('point-cloud-update', { detail: points }));
  }
};

const handleRecordToggle = (isRecording) => {
  console.log('Recording:', isRecording ? 'started' : 'stopped');
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