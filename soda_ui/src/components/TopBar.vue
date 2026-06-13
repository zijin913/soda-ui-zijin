<template>
<header class="top-bar">
    <div class="top-bar-content">
      <!-- Logo -->
      <div class="icon-box logo-box">
        <LogoIcon />
      </div>

      <!-- Center toolbar -->
      <div class="toolbar-group">
        <!-- Mode Toggle — disabled until backend is up (RT/RP set backend mode) -->
        <button class="tool-btn" :class="{ 'active': mode === 'realtime' }"
                :disabled="!isBackendUp"
                :title="backendDisabledTitle"
                @click="setMode('realtime')">
          <span class="mode-label">RT</span>
        </button>
        <button class="tool-btn" :class="{ 'active': mode === 'replay' }"
                :disabled="!isBackendUp"
                :title="backendDisabledTitle"
                @click="setMode('replay')">
          <span class="mode-label">RP</span>
        </button>

        <!-- Teleop (only in realtime mode) — launches scripts/teleop_quest.py
             via the backend. The OpenCV camera window + "Record this teleop?"
             prompt appear on the backend host's display. -->
        <button v-if="mode === 'realtime'" class="tool-btn teleop-btn" :class="{ 'active': isTeleopRunning }"
                :disabled="!isBackendUp"
                @click="toggleTeleop"
                :title="!isBackendUp ? backendDisabledTitle :
                        isTeleopRunning ? 'Stop teleop' : 'Start teleop (recording is asked in the camera window that pops up on the robot host)'">
          <span class="teleop-label" :class="{ 'running': isTeleopRunning }">TELE</span>
        </button>

        <!-- STOP / Recovery — kill EVERYTHING and start zero-gravity. Routes
             through /api/shutdown when the backend is alive, otherwise asks the
             launcher to spawn recover_zerog.py directly. Same end state. -->
        <button class="tool-btn stop-btn" @click="shutdownAll"
                :disabled="!canStop"
                :title="canStop ? 'Stop all processes and enter zero-gravity (hand-pose the arms back to home); then press q/ESC in the popup on the robot host to exit' : 'Nothing running'">
          <span class="stop-label">STOP</span>
        </button>

        <!-- Recordings Dropdown (only in replay mode) -->
        <div v-if="mode === 'replay'" class="recordings-dropdown-wrapper">
          <select v-model="selectedRecording" @change="loadRecording" class="recordings-select"
                  :disabled="!isBackendUp" :title="!isBackendUp ? backendDisabledTitle : ''">
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

      <!-- Phosphor status rail, pushed to the right. -->
      <div class="rail-slot">
        <StatusRail />
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import LogoIcon from '@/components/icons/LogoIcon.vue';
import HandToolIcon from '@/components/icons/HandToolIcon.vue';
import MoveToolIcon from '@/components/icons/MoveToolIcon.vue';
import SelectToolIcon from '@/components/icons/SelectToolIcon.vue';
import DropdownArrowIcon from '@/components/icons/DropdownArrowIcon.vue';
import ToolIndicatorIcon from '@/components/icons/ToolIndicatorIcon.vue';
import CoordinateIcon from '@/components/icons/Coordinate.vue';
import DepthToolIcon from '@/components/icons/DepthToolIcon.vue';
import StatusRail from '@/components/StatusRail.vue';
import { useConnectionStore } from '@/stores/connection';

const conn = useConnectionStore();
const isBackendUp = computed(() => conn.backend === 'up');
const canStop = computed(() => conn.launcher === 'up' && (conn.backend === 'up' || conn.hw === 'up'));
const backendDisabledTitle = computed(() =>
  conn.launcher === 'up'
    ? 'Backend is down — start it from the Launcher card'
    : 'Launcher not reachable — start `python -m soda_launcher` on the robot host',
);

const props = defineProps({
  modelValue: { type: String, default: 'hand' }
});

const emit = defineEmits(['update:modelValue', 'toggleDepth', 'teleopToggled', 'modeChanged', 'replayControl']);

const currentTool = ref(props.modelValue);
const isDropdownOpen = ref(false);
const isCoordinateActive = ref(false);
const isDepthActive = ref(false);
// Teleop running state lives in the connection store now (also visible from
// StatusRail). It's polled by the store; we just read it.
const isTeleopRunning = computed(() => conn.teleopRunning);
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
    const response = await fetch(`${conn.backendUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (response.ok) {
      // Refresh the store immediately so the button reflects reality without
      // waiting for the next 2s poll tick.
      await conn.pollTeleopOnce();
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
  // Always route through the launcher — it knows the mode and dispatches:
  //   sim:  kill_servers.sh (just kill everything; no zero-gravity)
  //   real: recover_zerog flow (kill + gravity-comp + OpenCV hand-pose popup)
  const isReal = conn.mode === 'real';
  const ok = window.confirm(
    isReal
      ? 'Stop all processes and enter zero-gravity?\n\n' +
        'The arms will become free to move by hand (gravity compensation).\n' +
        'On the robot host popup: hand-pose the arms back to home, then press\n' +
        'q / ESC to exit the whole program.'
      : 'Stop the sim and kill all processes?',
  );
  if (!ok) return;
  const r = await conn.stop();
  if (!r.ok) {
    window.alert(`Stop failed: ${r.error}`);
    return;
  }
  if (isReal) {
    window.alert('Stopping all processes and starting zero-gravity.\n' +
                 'On the robot host popup: hand-pose the arms back to home, then press q / ESC to exit.');
  }
};


const fetchRecordings = async () => {
  try {
    const response = await fetch(`${conn.backendUrl}/api/recordings`);
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
    const response = await fetch(`${conn.backendUrl}/api/mode/set`, {
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
    const response = await fetch(`${conn.backendUrl}/api/replay/load`, {
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
    const response = await fetch(`${conn.backendUrl}/api/replay/control`, {
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
  // Teleop polling is owned by the connection store; no local timer here.
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

.tool-btn:hover:not(:disabled), .tool-btn.active {
  background: #2D2F31;
}
.tool-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

/* StatusRail sits at the far right of the header. */
.rail-slot {
  margin-left: auto;
  display: flex;
  align-items: center;
  padding-right: 4px;
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

/* RT / RP buttons — phosphor amber when active (selected mode). */
.mode-label {
  font-size: 12px;
  font-weight: 700;
  color: #888;
  letter-spacing: 1px;
  transition: color 0.15s, text-shadow 0.15s;
}
.tool-btn.active .mode-label {
  color: #ffb020;
  text-shadow: 0 0 6px rgba(255,176,32,0.6);
}
.tool-btn.active {
  box-shadow: 0 0 0 1px rgba(255,176,32,0.25) inset;
}

/* TELE — phosphor green when running. */
.teleop-label {
  font-size: 12px;
  font-weight: 700;
  color: #888;
  letter-spacing: 1px;
  transition: color 0.15s, text-shadow 0.15s;
}
.teleop-label.running {
  color: #36e08a;
  text-shadow: 0 0 8px rgba(54,224,138,0.7);
  animation: tele-pulse 1.6s ease-in-out infinite;
}
.teleop-btn.active {
  background: #0d2118;
  box-shadow: 0 0 0 1px rgba(54,224,138,0.4) inset,
              0 0 14px rgba(54,224,138,0.25);
}
@keyframes tele-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.72; }
}

/* STOP — Pi-style diagonal red stripes + phosphor glow. */
.stop-btn {
  background-image:
    repeating-linear-gradient(45deg,
      rgba(74,21,18,0.55) 0px, rgba(74,21,18,0.55) 4px,
      rgba(20,8,7,0.55) 4px, rgba(20,8,7,0.55) 9px);
  border: 1px solid rgba(255,68,56,0.45);
  transition: all 0.15s;
}
.stop-btn:hover:not(:disabled) {
  border-color: rgba(255,68,56,0.85);
  box-shadow: 0 0 14px rgba(255,68,56,0.55);
  background-image:
    repeating-linear-gradient(45deg,
      rgba(74,21,18,0.85) 0px, rgba(74,21,18,0.85) 4px,
      rgba(20,8,7,0.85) 4px, rgba(20,8,7,0.85) 9px);
}
.stop-btn:disabled {
  border-color: rgba(255,68,56,0.18);
  background-image: none;
  background: transparent;
}
.stop-label {
  font-size: 12px;
  font-weight: 800;
  color: #ff4438;
  letter-spacing: 1.5px;
  text-shadow: 0 0 6px rgba(255,68,56,0.55);
}
.stop-btn:disabled .stop-label {
  color: #62717f;
  text-shadow: none;
}

.replay-controls {
  display: flex;
  gap: 4px;
}

.control-icon {
  font-size: 16px;
}
</style>