<template>
  <aside class="right-sidebar">
    <!-- Gripper 模块 -->
    <div class="panel-block gripper-block">
      <div class="panel-header">
        <GripperIcon />
        <span>Gripper</span>
      </div>
      <div class="gripper-value">
        <span class="val">20</span>
        <span class="unit">mm</span>
      </div>
    </div>

    <!-- Velocity / Charts 模块 -->
    <div class="panel-block velocity-block">
      <!-- Switch Bar -->
      <div class="switch-bar">
        <div class="switch-pill" :class="{ active: activeTab === 'Angle' }" @click="activeTab = 'Angle'">Angle</div>
        <div class="switch-pill" :class="{ active: activeTab === 'Velocity' }" @click="activeTab = 'Velocity'">Velocity</div>
        <div class="switch-pill" :class="{ active: activeTab === 'Torque' }" @click="activeTab = 'Torque'">Torque</div>
      </div>

      <!-- Charts List -->
      <div class="charts-container">
        <div v-for="id in sortedJointIds" :key="id" class="chart-row">
          <div class="chart-label">{{ jointNames[id] || `Joint ${id}` }}</div>
          <div class="chart-visual">
            <div class="y-axis"><span>1</span><span>0</span><span>-1</span><span>-2</span></div>
            <div class="waveform">
              <svg width="100%" height="100%" viewBox="0 0 100 50" preserveAspectRatio="none">
                <path :d="generatePath(id)" fill="none" stroke="#3DCDA5" stroke-width="1.5" vector-effect="non-scaling-stroke" />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref, computed } from 'vue';
import GripperIcon from '@/components/icons/GripperIcon.vue';

const props = defineProps({
  historyData: { type: Object, required: true },
  jointNames: { type: Object, default: () => ({}) }
});

const activeTab = ref('Angle');

const sortedJointIds = computed(() => {
  return Object.keys(props.historyData).map(Number).sort((a, b) => a - b);
});

// SVG Path Generator
const generatePath = (jointIndex) => {
  let data;
  const jointData = props.historyData[jointIndex];

  if (!jointData) return "M0 25 L100 25";

  if (activeTab.value === 'Angle') data = jointData.angle;
  else if (activeTab.value === 'Velocity') data = jointData.velocity;
  else if (activeTab.value === 'Torque') data = jointData.torque;

  if (!data || data.length === 0) return "M0 25 L100 25";

  const width = 100;
  const height = 50;
  // 假设 max_history 为 500
  const maxHistory = 500;
  const step = width / (maxHistory - 1);
  const range = 6;
  const mid = height / 2;
  const scaleY = (height * 0.8) / range;

  let path = `M0 ${mid}`;

  data.forEach((val, index) => {
    const x = index * step;
    const y = mid - (val * scaleY);
    if (index === 0) path = `M${x} ${y}`;
    else path += ` L${x} ${y}`;
  });

  return path;
};
</script>

<style scoped>
.right-sidebar {
  position: absolute;
  right: 24px;
  top: 0;
  bottom: 24px;
  width: 371px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: hidden;
  z-index: 20;
}

.panel-block {
  background: rgba(29, 29, 29, 0.9);
  border-radius: 32px;
  padding: 20px;
  backdrop-filter: blur(10px);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 18px;
  color: white;
}

.gripper-block {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 80px;
}

.gripper-value {
  background: #464646;
  border-radius: 4px;
  padding: 4px 8px;
  display: flex;
  align-items: baseline;
  gap: 4px;
  color: white;
}

.velocity-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.switch-bar {
  background: #2D2F31;
  border-radius: 32px;
  display: flex;
  padding: 4px;
  margin-bottom: 20px;
}

.switch-pill {
  flex: 1;
  text-align: center;
  padding: 8px 0;
  font-size: 14px;
  color: #888;
  cursor: pointer;
  border-radius: 24px;
}
.switch-pill.active { background: #3C3E40; color: white; }

.charts-container {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
}
.charts-container::-webkit-scrollbar { width: 6px; }
.charts-container::-webkit-scrollbar-thumb { background: #555; border-radius: 3px; }

.chart-row { margin-bottom: 16px; }
.chart-label { font-size: 12px; color: #aaa; margin-bottom: 4px; }
.chart-visual { height: 76px; position: relative; display: flex; align-items: center; }
.y-axis { display: flex; flex-direction: column; justify-content: space-between; height: 100%; font-size: 10px; color: #666; margin-right: 8px; }
.waveform {
  flex: 1; height: 100%;
  border-left: 2px solid #444645;
  border-bottom: 2px solid #444645;
  background: rgba(0, 0, 0, 0.2);
}
</style>