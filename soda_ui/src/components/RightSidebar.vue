<template>
  <aside class="right-sidebar">
    <!-- Gripper 模块 -->
    <div class="panel-block gripper-block">
      <div class="panel-header">
        <GripperIcon />
        <span>Gripper</span>
      </div>
      <div
        v-for="side in grippersToShow"
        :key="side"
        class="gripper-controls"
      >
        <span v-if="dualMode" class="side-tag" :class="`side-tag-${side}`">{{ side === 'left' ? 'L' : 'R' }}</span>
        <div class="slider-wrapper">
          <input
            type="range"
            class="gripper-slider"
            :value="targetGripperValues[side]"
            min="10"
            max="100"
            @input="onSliderInput(side, $event)"
          />
          <div
            class="current-indicator"
            :style="{ left: currentIndicatorLeft(side) }"
          ></div>
        </div>
        <div class="gripper-value">
          <span class="val">{{ targetGripperValues[side] }}</span>
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

      <!-- Legend (dual mode) -->
      <div v-if="dualMode && mode !== 'replay'" class="legend">
        <span><i class="dot dot-left"></i>Left</span>
        <span><i class="dot dot-right"></i>Right</span>
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
            <div class="y-axis">
              <span v-for="(label, idx) in getYAxisLabels(id)" :key="idx">{{ label }}</span>
            </div>
            <div class="waveform">
              <svg width="100%" height="100%" viewBox="0 0 500 50" preserveAspectRatio="none">
                <!-- Left arm (also used for single-arm and replay) -->
                <path :d="generatePath(id, 'left')" fill="none" stroke="#3DCDA5" stroke-width="1.5" vector-effect="non-scaling-stroke" />
                <!-- Right arm (dual mode realtime) -->
                <path
                  v-if="dualMode && mode !== 'replay'"
                  :d="generatePath(id, 'right')"
                  fill="none"
                  stroke="#F0833A"
                  stroke-width="1.5"
                  vector-effect="non-scaling-stroke"
                />

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
import { ref, computed, watch } from 'vue';
import GripperIcon from '@/components/icons/GripperIcon.vue';

const props = defineProps({
  historyData: { type: Object, required: true },     // { left: { id: {angle,velocity,torque} }, right: {...} }
  // Per-(side,id) baseline angle, captured when the joint first appears. The
  // chart plots (val - baseline) for the Angle tab so motion is visible even
  // when the joint rests far from absolute zero (e.g. shoulder pitch at -1.5 rad).
  baselines: { type: Object, default: () => ({ left: {}, right: {} }) },
  jointNames: { type: Object, default: () => ({}) },
  gripperDistances: { type: Object, default: () => ({ left: 0, right: 0 }) },
  dualMode: { type: Boolean, default: false },
  fullData: { type: Object, default: () => ({}) },
  mode: { type: String, default: 'realtime' },
  currentFrame: { type: Number, default: 0 },
  totalFrames: { type: Number, default: 0 }
});

const emit = defineEmits(['gripper-change']);

const targetGripperValues = ref({
  left: Math.round(props.gripperDistances.left) || 10,
  right: Math.round(props.gripperDistances.right) || 10,
});
const userInteracted = ref({ left: false, right: false });

const grippersToShow = computed(() => props.dualMode ? ['left', 'right'] : ['left']);

watch(() => props.gripperDistances, (val) => {
  for (const side of ['left', 'right']) {
    if (!userInteracted.value[side] && typeof val?.[side] === 'number') {
      targetGripperValues.value[side] = Math.round(val[side]);
    }
  }
}, { deep: true });

const onSliderInput = (side, event) => {
  userInteracted.value[side] = true;
  const val = Number(event.target.value);
  targetGripperValues.value[side] = val;
  emit('gripper-change', { side, value: val });
  if (window.sendGripperSet) {
    // Keep single-arm call signature unchanged (no side arg) so existing backends stay happy.
    if (props.dualMode) window.sendGripperSet(val, side);
    else window.sendGripperSet(val);
  }
};

const currentIndicatorLeft = (side) => {
  const val = props.gripperDistances?.[side] ?? 0;
  const min = 10;
  const max = 100;
  const clamped = Math.max(min, Math.min(max, val));
  const percent = (clamped - min) / (max - min);
  // (100% - 16px) is the track width between thumb centers; +4px centers the 8px indicator.
  return `calc((100% - 16px) * ${percent} + 4px)`;
};

const activeTab = ref('Angle');
const VIEW_WINDOW = 500; // Frames to show in window

// Symmetric ±half-range per tab. Keeps 0 at the chart vertical midline so
// every chart's zero line is aligned, and zooms in tighter than URDF limits
// so small fluctuations stay visible. Tweak here to taste.
const VIEW_HALF_RANGE = {
  Angle: 1.0,    // ±1.0 rad (~57°)
  Velocity: 0.5, // ±0.5 rad/s
  Torque: 10,    // ±10 Nm
};

const sortedJointIds = computed(() => {
  if (props.mode === 'replay') {
    return Object.keys(props.fullData).map(Number).sort((a, b) => a - b);
  }
  // Realtime: union of joint ids across both arms
  const ids = new Set([
    ...Object.keys(props.historyData?.left || {}),
    ...Object.keys(props.historyData?.right || {}),
  ]);
  return [...ids].map(Number).sort((a, b) => a - b);
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

const getYAxisLabels = () => {
  const m = VIEW_HALF_RANGE[activeTab.value] ?? 1;
  // Top/middle/bottom — symmetric around zero
  return [`+${m}`, '0', `-${m}`];
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
const generatePath = (jointIndex, side = 'left') => {
  let data;

  // For Angle, subtract a baseline so the chart shows deviation from rest
  // (otherwise a joint resting at e.g. -1.5 rad sits outside the ±1.0 view).
  // Realtime: baseline captured by App.vue on first observation per (side, id).
  // Replay: baseline = first frame of the trajectory.
  let baseline = 0;

  if (props.mode === 'realtime') {
    const jointData = props.historyData?.[side]?.[jointIndex];
    if (!jointData) return `M0 25 L${VIEW_WINDOW} 25`;

    if (activeTab.value === 'Angle') {
      data = jointData.angle;
      baseline = props.baselines?.[side]?.[jointIndex] ?? 0;
    } else if (activeTab.value === 'Velocity') data = jointData.velocity;
    else if (activeTab.value === 'Torque') data = jointData.torque;
  } else {
    // Replay Mode
    const jointData = props.fullData[jointIndex];
    if (!jointData) return `M0 25 L${VIEW_WINDOW} 25`;

    let fullList;
    if (activeTab.value === 'Angle') {
      fullList = jointData.angle;
      baseline = (fullList && fullList.length > 0) ? fullList[0] : 0;
    } else if (activeTab.value === 'Velocity') fullList = jointData.velocity;
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
  
  const halfRange = VIEW_HALF_RANGE[activeTab.value] ?? 1;
  const minVal = -halfRange;
  const maxVal = halfRange;
  
  const range = maxVal - minVal;
  const yTop = height * 0.1;
  const yBottom = height * 0.9;
  const mapY = (val) => {
    // Clamp into the view window so values outside the symmetric range still
    // render — they pin to the top or bottom edge instead of disappearing
    // off-canvas (e.g. a joint resting at -1.5 rad with a ±1.0 view).
    const clamped = Math.min(maxVal, Math.max(minVal, val));
    const pct = (clamped - minVal) / (range || 1);
    // SVG y=0 is top, so larger values map closer to yTop
    return yBottom - pct * (yBottom - yTop);
  };

  let path = '';

  data.forEach((val, index) => {
    const x = index * step;
    const y = mapY(val - baseline);
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

.slider-wrapper {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
  height: 20px;
}

.current-indicator {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 8px;
  height: 8px;
  background: #FF5555;
  border-radius: 50%;
  pointer-events: none;
  z-index: 3;
  box-shadow: 0 0 2px rgba(0,0,0,0.5);
  transition: left 0.1s linear;
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

.legend {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: #aaa;
  margin: -8px 0 12px 4px;
}
.legend .dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.legend .dot-left { background: #3DCDA5; }
.legend .dot-right { background: #F0833A; }

.side-tag {
  font-size: 11px;
  font-weight: 600;
  width: 16px;
  text-align: center;
  color: #aaa;
}
.side-tag-left { color: #3DCDA5; }
.side-tag-right { color: #F0833A; }

.charts-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  padding-right: 4px;
}
.charts-container::-webkit-scrollbar { width: 6px; }
.charts-container::-webkit-scrollbar-thumb { background: #555; border-radius: 3px; }

.chart-row { flex: 1; min-height: 60px; display: flex; flex-direction: column; }
.chart-header-row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; flex: 0 0 auto; }
.chart-label { font-size: 12px; color: #aaa; }
.current-value { font-size: 12px; color: #3DCDA5; font-family: 'Inter', monospace; }

.chart-visual { flex: 1; min-height: 0; position: relative; display: flex; align-items: stretch; }
.y-axis { display: flex; flex-direction: column; justify-content: space-between; height: 100%; font-size: 10px; color: #666; margin-right: 8px; }
.waveform {
  flex: 1; height: 100%;
  border-left: 2px solid #444645;
  border-bottom: 2px solid #444645;
  background: rgba(0, 0, 0, 0.2);
}
</style>