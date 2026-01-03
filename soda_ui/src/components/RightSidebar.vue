<template>
  <aside class="right-sidebar">
    <!-- Gripper 模块 -->
    <div class="panel-block gripper-block">
      <div class="panel-header">
        <GripperIcon />
        <span>Gripper</span>
      </div>
       <div class="gripper-controls">
         <input
           type="range"
           class="gripper-slider"
           v-model="gripperValue"
           min="10"
           max="100"
         />
         <div class="gripper-value">
           <span class="val">{{ gripperValue }}</span>
           <span class="unit">mm</span>
         </div>
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
          <div class="chart-header-row">
            <div class="chart-label">{{ jointNames[id] || `Joint ${id}` }}</div>
            <div v-if="mode === 'replay'" class="current-value">
              {{ getCurrentValue(id) }}
            </div>
          </div>
          <div class="chart-visual">
            <div class="y-axis"><span>1</span><span>0</span><span>-1</span><span>-2</span></div>
            <div class="waveform">
              <svg width="100%" height="100%" viewBox="0 0 500 50" preserveAspectRatio="none">
                <!-- Data Path -->
                <path :d="generatePath(id)" fill="none" stroke="#3DCDA5" stroke-width="1.5" vector-effect="non-scaling-stroke" />
                
                <!-- Playhead Line (Replay Mode) -->
                <line 
                  v-if="mode === 'replay'"
                  :x1="getCursorX() + 0.5" 
                  y1="0" 
                  :x2="getCursorX() + 0.5" 
                  y2="50" 
                  stroke="#FFFFFF" 
                  stroke-width="1"
                  shape-rendering="crispEdges"
                />
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
  jointNames: { type: Object, default: () => ({}) },
  gripperDistance: { type: Number, default: 0 },
  fullData: { type: Object, default: () => ({}) },
  mode: { type: String, default: 'realtime' },
  currentFrame: { type: Number, default: 0 },
  totalFrames: { type: Number, default: 0 }
});

const emit = defineEmits(['gripper-change']);

const gripperValue = computed({
  get: () => Math.round(props.gripperDistance),
  set: (value) => {
    emit('gripper-change', value);
    if (window.sendGripperSet) {
      window.sendGripperSet(value);
    }
  }
});

const activeTab = ref('Angle');
const VIEW_WINDOW = 500; // Frames to show in window

const sortedJointIds = computed(() => {
  const source = props.mode === 'replay' ? props.fullData : props.historyData;
  return Object.keys(source).map(Number).sort((a, b) => a - b);
});

const getWindowStart = () => {
  if (props.mode !== 'replay') return 0;
  // If current frame < half window, start at 0
  // Else start at current - half
  const half = Math.floor(VIEW_WINDOW / 2);
  return Math.max(0, props.currentFrame - half);
};

const getCursorX = () => {
  if (props.mode !== 'replay') return 0;
  const start = getWindowStart();
  const relativeIndex = props.currentFrame - start;
  // SVG viewBox width is 500 (matching VIEW_WINDOW for 1:1 mapping)
  return relativeIndex; 
};

const getCurrentValue = (id) => {
  if (props.mode !== 'replay' || !props.fullData[id]) return '';
  let val = 0;
  const jointData = props.fullData[id];
  const idx = props.currentFrame;
  
  if (activeTab.value === 'Angle') val = jointData.angle[idx];
  else if (activeTab.value === 'Velocity') val = jointData.velocity[idx];
  else if (activeTab.value === 'Torque') val = jointData.torque[idx];
  
  return val !== undefined ? val.toFixed(3) : '';
};

// SVG Path Generator
const generatePath = (jointIndex) => {
  let data;
  
  if (props.mode === 'realtime') {
    const jointData = props.historyData[jointIndex];
    if (!jointData) return `M0 25 L${VIEW_WINDOW} 25`;
    
    if (activeTab.value === 'Angle') data = jointData.angle;
    else if (activeTab.value === 'Velocity') data = jointData.velocity;
    else if (activeTab.value === 'Torque') data = jointData.torque;
  } else {
    // Replay Mode
    const jointData = props.fullData[jointIndex];
    if (!jointData) return `M0 25 L${VIEW_WINDOW} 25`;
    
    let fullList;
    if (activeTab.value === 'Angle') fullList = jointData.angle;
    else if (activeTab.value === 'Velocity') fullList = jointData.velocity;
    else if (activeTab.value === 'Torque') fullList = jointData.torque;
    
    // Slice for window
    const start = getWindowStart();
    const end = start + VIEW_WINDOW;
    data = fullList ? fullList.slice(start, end) : [];
  }

  if (!data || data.length === 0) return `M0 25 L${VIEW_WINDOW} 25`;

  const width = 500; // Match viewBox
  const height = 50;
  // X step is 1 since width=500 and data len <= 500
  const step = 1; 
  const range = 6; // Y range assumption
  const mid = height / 2;
  const scaleY = (height * 0.8) / range;

  let path = `M0 ${mid}`;

  data.forEach((val, index) => {
    const x = index * step;
    const y = mid - (val * scaleY);
    // Clamp Y to stay within visual bounds? SVG clip handles it but clamped path is cleaner
    // const clampedY = Math.max(0, Math.min(height, y));
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
  flex-direction: column;
  gap: 12px;
  padding: 16px 20px;
}

.gripper-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.gripper-value {
  background: #464646;
  border-radius: 4px;
  padding: 4px 8px;
  display: flex;
  align-items: baseline;
  gap: 4px;
  color: white;
  width: fit-content;
}

.gripper-slider {
  -webkit-appearance: none;
  appearance: none;
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: #2D2F31;
  outline: none;
  cursor: pointer;
}

.gripper-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #3DCDA5;
  cursor: pointer;
}

.gripper-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #3DCDA5;
  cursor: pointer;
  border: none;
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
.chart-header-row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; }
.chart-label { font-size: 12px; color: #aaa; }
.current-value { font-size: 12px; color: #3DCDA5; font-family: 'Inter', monospace; }

.chart-visual { height: 76px; position: relative; display: flex; align-items: center; }
.y-axis { display: flex; flex-direction: column; justify-content: space-between; height: 100%; font-size: 10px; color: #666; margin-right: 8px; }
.waveform {
  flex: 1; height: 100%;
  border-left: 2px solid #444645;
  border-bottom: 2px solid #444645;
  background: rgba(0, 0, 0, 0.2);
}
</style>