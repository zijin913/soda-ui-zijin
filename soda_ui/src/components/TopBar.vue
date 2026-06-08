<template>
<header class="top-bar">
    <div class="top-bar-content">
      <!-- Logo -->
      <div class="icon-box logo-box">
        <LogoIcon />
      </div>

      <!-- Center toolbar -->
      <div class="toolbar-group">
        <!-- Mode Toggle -->
        <button class="tool-btn" :class="{ 'active': mode === 'realtime' }" @click="setMode('realtime')">
          <span class="mode-label">RT</span>
        </button>
        <button class="tool-btn" :class="{ 'active': mode === 'replay' }" @click="setMode('replay')">
          <span class="mode-label">RP</span>
        </button>

        <!-- Teleop (only in realtime mode) — launches scripts/teleop_quest.py
             via the backend. The OpenCV camera window + "Record this teleop?"
             prompt appear on the backend host's display. -->
        <button v-if="mode === 'realtime'" class="tool-btn teleop-btn" :class="{ 'active': isTeleopRunning }"
                @click="toggleTeleop"
                :title="isTeleopRunning ? 'Stop teleop' : 'Start teleop (recording is asked in the camera window that pops up on the robot host)'">
          <span class="teleop-label" :class="{ 'running': isTeleopRunning }">TELE</span>
        </button>

        <!-- STOP / Recovery — kill EVERYTHING and start zero-gravity so the
             operator can hand-pose the arms back to home. A popup appears on
             the robot host (the UI goes dark once the backend is killed). -->
        <button class="tool-btn stop-btn" @click="shutdownAll"
                title="Stop all processes and enter zero-gravity (hand-pose the arms back to home); then press q/ESC in the popup on the robot host to exit">
          <span class="stop-label">STOP</span>
        </button>

        <!-- Recordings Dropdown (only in replay mode) -->
        <div v-if="mode === 'replay'" class="recordings-dropdown-wrapper">
          <select v-model="selectedRecording" @change="loadRecording" class="recordings-select">
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
import { ref, onMounted, onUnmounted } from 'vue';
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

const emit = defineEmits(['update:modelValue', 'toggleDepth', 'teleopToggled', 'modeChanged', 'replayControl']);

const currentTool = ref(props.modelValue);
const isDropdownOpen = ref(false);
const isCoordinateActive = ref(false);
const isDepthActive = ref(false);
const isTeleopRunning = ref(false);       // teleop subprocess running on the backend host
let teleopStatusTimer = null;
const recordingFiles = ref([]);
const selectedRecording = ref('');
const mode = ref('realtime');

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

// Start/stop teleop. The backend spawns scripts/teleop_quest.py --windowed
// (OpenCV camera + "Record this teleop?" prompt render on the backend host).
const toggleTeleop = async () => {
  const path = isTeleopRunning.value ? '/api/teleop/stop' : '/api/teleop/start';
  try {
    const response = await fetch(`http://localhost:8080${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (response.ok) {
      await fetchTeleopStatus();
      emit('teleopToggled', isTeleopRunning.value);
    }
  } catch (error) {
    console.error('Failed to toggle teleop:', error);
  }
};

// STOP / Recovery: kill everything + start zero-gravity for hand-posing.
// Destructive — confirm first. The backend spawns a detached helper that
// survives its own death and shows a popup on the robot host.
const shutdownAll = async () => {
  const ok = window.confirm(
    'Stop all processes and enter zero-gravity?\n\n' +
    'The arms will become free to move by hand (gravity compensation). The UI\n' +
    'will go dark once stopped. On the robot host popup: hand-pose the arms back\n' +
    'to home, then press q / ESC to exit the whole program.');
  if (!ok) return;
  try {
    await fetch('http://localhost:8080/api/shutdown', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
  } catch (error) {
    // backend is being killed — losing the connection is expected.
  }
  window.alert('Stopping all processes and starting zero-gravity.\n' +
               'On the robot host popup: hand-pose the arms back to home, then press q / ESC to exit.');
};

// Poll teleop status so the button reflects reality (teleop can also exit
// itself via the 'q' key in its OpenCV window).
const fetchTeleopStatus = async () => {
  try {
    const response = await fetch('http://localhost:8080/api/teleop/status');
    if (response.ok) {
      const data = await response.json();
      isTeleopRunning.value = !!data.running;
    }
  } catch (error) {
    // backend not up yet — leave state as-is
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

const setMode = async (newMode) => {
  try {
    const response = await fetch('http://localhost:8080/api/mode/set', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ mode: newMode })
    });

    if (response.ok) {
      mode.value = newMode;
      emit('modeChanged', newMode);
      if (newMode === 'replay') {
        await fetchRecordings();
      }
    }
  } catch (error) {
    console.error('Failed to set mode:', error);
  }
};

const loadRecording = async () => {
  if (!selectedRecording.value) return;

  try {
    const response = await fetch('http://localhost:8080/api/replay/load', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ filename: selectedRecording.value })
    });

    if (response.ok) {
      const data = await response.json();
      console.log('Recording loaded:', data);
      emit('recordingLoaded', selectedRecording.value);
    }
  } catch (error) {
    console.error('Failed to load recording:', error);
  }
};

const replayControl = async (action) => {
  try {
    const response = await fetch('http://localhost:8080/api/replay/control', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ action })
    });

    if (response.ok) {
      const data = await response.json();
      emit('replayControl', action, data);
    }
  } catch (error) {
    console.error('Failed to control replay:', error);
  }
};

onMounted(() => {
  fetchRecordings();
  fetchTeleopStatus();
  teleopStatusTimer = setInterval(fetchTeleopStatus, 2000);
});

onUnmounted(() => {
  if (teleopStatusTimer) clearInterval(teleopStatusTimer);
});
</script>

<style scoped>
/* .top-bar styles moved here from App.vue */
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

.mode-label {
  font-size: 12px;
  font-weight: bold;
  color: #888;
}

.mode-label.active {
  color: white;
}

.teleop-label {
  font-size: 12px;
  font-weight: bold;
  color: #888;
  letter-spacing: 0.5px;
}

.teleop-label.running {
  color: #4caf50;
}

.teleop-btn.active {
  background: #1f3a23;
}

.stop-label {
  font-size: 12px;
  font-weight: bold;
  color: #f44336;
  letter-spacing: 0.5px;
}

.stop-btn:hover {
  background: #3a1f1f;
}

.replay-controls {
  display: flex;
  gap: 4px;
}

.control-icon {
  font-size: 16px;
}
</style>