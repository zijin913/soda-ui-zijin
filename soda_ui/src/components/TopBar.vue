<template>
<header class="top-bar">
    <div class="top-bar-content">
      <!-- Logo -->
      <div class="icon-box logo-box">
        <LogoIcon />
      </div>

      <!-- 中间工具栏 -->
      <div class="toolbar-group">
        <!-- Record -->
        <button class="tool-btn" :class="{ 'active': isRecording }" @click="toggleRecord">
          <div class="record-dot" :class="{ 'recording': isRecording }"></div>
        </button>

        <!-- Recordings Dropdown -->
        <div class="recordings-dropdown-wrapper">
          <select v-model="selectedRecording" class="recordings-select">
            <option value="">Select Recording</option>
            <option v-for="file in recordingFiles" :key="file" :value="file">
              {{ file }}
            </option>
          </select>
        </div>

        <div class="divider"></div>

        <!-- Mouse Tool -->
        <div class="tool-btn-group">
          <button class="tool-btn active">
            <HandToolIcon v-if="currentTool === 'hand'" />
            <MoveToolIcon v-if="currentTool === 'move'" />
            <SelectToolIcon v-if="currentTool === 'select'" />
          </button>
          <button class="tool-arrow" @click="toggleDropdown">
            <DropdownArrowIcon />
          </button>

          <!-- Mouse Tool Dropdown -->
          <div v-if="isDropdownOpen" class="mouse-tool-dropdown">
            <button class="dropdown-item" @click="selectTool('hand')">
              <div class="dropdown-icon-text">
                <ToolIndicatorIcon class="tool-indicator" :class="{ 'active': currentTool === 'hand' }" />
                <HandToolIcon />
                <span>Hand Tool</span>
              </div>
            </button>
            <button class="dropdown-item" @click="selectTool('move')">
              <div class="dropdown-icon-text">
                <ToolIndicatorIcon class="tool-indicator" :class="{ 'active': currentTool === 'move' }" />
                <MoveToolIcon />
                <span>Move</span>
              </div>
            </button>
            <button class="dropdown-item" @click="selectTool('select')">
              <div class="dropdown-icon-text">
                <ToolIndicatorIcon class="tool-indicator" :class="{ 'active': currentTool === 'select' }" />
                <SelectToolIcon />
                <span>Select</span>
              </div>
            </button>
          </div>
        </div>

        <button class="tool-btn" :class="{ 'active': isCoordinateActive }" @click="toggleCoordinate">
          <CoordinateIcon />
        </button>

        <!-- Depth Tools -->
        <button class="tool-btn" :class="{ 'active': isDepthActive }" @click="toggleDepth">
          <DepthToolIcon />
        </button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import LogoIcon from '@/components/icons/LogoIcon.vue';
import HandToolIcon from '@/components/icons/HandToolIcon.vue';
import MoveToolIcon from '@/components/icons/MoveToolIcon.vue';
import SelectToolIcon from '@/components/icons/SelectToolIcon.vue';
import DropdownArrowIcon from '@/components/icons/DropdownArrowIcon.vue';
import ToolIndicatorIcon from '@/components/icons/ToolIndicatorIcon.vue';
import CoordinateIcon from '@/components/icons/Coordinate.vue';
import DepthToolIcon from '@/components/icons/DepthToolIcon.vue';

const props = defineProps({
  modelValue: { type: String, default: 'hand' }
});

const emit = defineEmits(['update:modelValue', 'toggleDepth', 'toggleRecord']);

const currentTool = ref(props.modelValue);
const isDropdownOpen = ref(false);
const isCoordinateActive = ref(false);
const isDepthActive = ref(false);
const isRecording = ref(false);
const recordingFiles = ref([]);
const selectedRecording = ref('');

const toggleDropdown = () => {
  isDropdownOpen.value = !isDropdownOpen.value;
};

const selectTool = (tool) => {
  currentTool.value = tool;
  emit('update:modelValue', tool);
  isDropdownOpen.value = false;
};

const toggleCoordinate = () => {
  isCoordinateActive.value = !isCoordinateActive.value;
};

const toggleDepth = () => {
  isDepthActive.value = !isDepthActive.value;
  emit('toggleDepth', isDepthActive.value);
};

const toggleRecord = async () => {
  isRecording.value = !isRecording.value;
  const action = isRecording.value ? 'start' : 'stop';
  try {
    const response = await fetch('http://localhost:8080/api/record', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ action })
    });
    if (response.ok) {
      emit('toggleRecord', isRecording.value);
      await fetchRecordings();
    } else {
      isRecording.value = !isRecording.value; // Revert on failure
    }
  } catch (error) {
    console.error('Failed to toggle recording:', error);
    isRecording.value = !isRecording.value; // Revert on error
  }
};

const fetchRecordings = async () => {
  try {
    const response = await fetch('http://localhost:8080/api/recordings');
    if (response.ok) {
      const data = await response.json();
      recordingFiles.value = data.files || [];
    }
  } catch (error) {
    console.error('Failed to fetch recordings:', error);
  }
};

onMounted(() => {
  fetchRecordings();
});
</script>

<style scoped>
/* 将 App.vue 中关于 .top-bar 的样式移动到这里 */
.top-bar {
  height: 90px;
  padding: 12px 24px;
  z-index: 50;
  width: 100%;
  box-sizing: border-box;
}

.top-bar-content {
  background: #141414;
  border-radius: 24px;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  padding: 0 12px;
  position: relative;
}

.logo-box {
  width: 58px;
  height: 58px;
  background: #2D2F31;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 20px;
}

.toolbar-group {
  display: flex;
  gap: 12px;
  align-items: center;
}

.divider {
  width: 1px;
  height: 40px;
  background: #424548;
  margin: 0 8px;
}

.tool-btn {
  width: 58px;
  height: 58px;
  border: none;
  background: transparent;
  border-radius: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
}

.tool-btn:hover, .tool-btn.active {
  background: #2D2F31;
}

.tool-btn-group {
  display: flex;
  /* background: #424548; */
  border-radius: 10px;
  padding: 0 4px;
  align-items: center;
  height: 58px;
  position: relative;
}


.record-dot {
  width: 24px;
  height: 24px;
  background: #F44336;
  border-radius: 50%;
  border: 4px solid #fff;
  transition: all 0.3s;
}

.record-dot.recording {
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.mouse-tool-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  background: #2D2F31;
  border-radius: 10px;
  padding: 8px 0;
  width: 150px;
  z-index: 100;
  margin-top: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.dropdown-item {
  width: 100%;
  background: transparent;
  border: none;
  color: white;
  padding: 8px 12px;
  text-align: left;
  cursor: pointer;
}
.dropdown-item:hover { background: #424548; }

.dropdown-icon-text {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-arrow {
  background: none;
  border: none;
  color: white;
  padding: 0 8px;
  cursor: pointer;
}

.tool-indicator {
  width: 11px;
  height: 11px;
  margin-right: 8px;
  opacity: 0;
  transition: opacity 0.2s;
  flex-shrink: 0;
}

.tool-indicator.active {
  opacity: 1;
}

.recordings-dropdown-wrapper {
  display: flex;
  align-items: center;
  margin-left: 4px;
}

.recordings-select {
  background: #2D2F31;
  color: white;
  border: none;
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  cursor: pointer;
  outline: none;
  min-width: 120px;
  max-width: 200px;
}

.recordings-select:hover {
  background: #424548;
}

.recordings-select option {
  background: #2D2F31;
  color: white;
}
</style>