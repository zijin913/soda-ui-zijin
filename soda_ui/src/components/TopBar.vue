<template>
<header class="top-bar">
    <div class="top-bar-content">
      <!-- Logo -->
      <div class="icon-box logo-box">
        <LogoIcon />
      </div>

      <!-- Center toolbar -->
      <div class="toolbar-group">
        <!-- Mode Toggle (RT / RP) — single segmented amber pill, the active
             half lit up. Disabled until backend is up. -->
        <div class="mode-toggle">
          <button class="tool-btn mode-btn" :class="{ 'active': mode === 'realtime' }"
                  :disabled="!isBackendUp"
                  :title="backendDisabledTitle"
                  @click="setMode('realtime')">
            <span class="mode-label">RT</span>
          </button>
          <button class="tool-btn mode-btn" :class="{ 'active': mode === 'replay' }"
                  :disabled="!isBackendUp"
                  :title="backendDisabledTitle"
                  @click="setMode('replay')">
            <span class="mode-label">RP</span>
          </button>
        </div>

        <!-- Teleop (only in realtime mode) — launches scripts/teleop_quest.py
             via the backend. Green-phosphor: matches the in-UI overlay aesthetic
             and signals "live data flowing" (distinct from HOME cyan and
             STOP red). -->
        <button v-if="mode === 'realtime'" class="tool-btn teleop-btn" :class="{ 'active': isTeleopRunning }"
                :disabled="!isBackendUp"
                @click="toggleTeleop"
                :title="!isBackendUp ? backendDisabledTitle :
                        isTeleopRunning ? 'Stop teleop' : 'Start teleop (recording is asked in the camera window that pops up on the robot host)'">
          <span class="teleop-label" :class="{ 'running': isTeleopRunning }">TELE</span>
        </button>

        <!-- HOME — move both arms to home pose. During teleop routes through
             teleop_quest's 'h' key (clears pending target + pauses) so it
             doesn't race teleop's command stream. Otherwise POSTs /robot/home. -->
        <button class="tool-btn home-btn"
                :disabled="!isBackendUp || conn.homing"
                @click="onHome"
                :title="!isBackendUp ? backendDisabledTitle :
                        conn.homing ? 'Homing in progress…' : 'Move both arms to home pose'">
          <span class="home-label">{{ conn.homing ? 'HOMING…' : 'HOME' }}</span>
        </button>

        <!-- STOP / Recovery — opens a phosphor confirm modal; on real mode
             confirms transition into zero-gravity recovery handled fully in-UI
             by RecoveryModal (no more OpenCV popup). -->
        <button class="tool-btn stop-btn" @click="conn.openStopConfirm"
                :disabled="!canStop"
                :title="canStop ? 'Stop all processes; on real mode you get an in-UI zero-gravity recovery overlay' : 'Nothing running'">
          <span class="stop-label">STOP</span>
        </button>

        <!-- Emergency stop lives in the fixed top-right corner (EmergencyStop
             component, mounted at App.vue root) — single-click instant SIGKILL,
             intentionally kept out of this toolbar to avoid mis-clicks. -->

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

      <!-- Emergency stop — embedded at the far-right end of the bar, set apart
           from the status rail. Single-click instant SIGKILL of the whole
           stack (no modal, no hold). -->
      <EmergencyStop />
    </div>

    <!-- Modals are mounted at App.vue root (stacking-context reasons), TopBar
         just dispatches open events through the connection store. -->
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
import EmergencyStop from '@/components/EmergencyStop.vue';
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

// HOME — connection store handles the teleop/non-teleop routing.
const onHome = async () => {
  const r = await conn.goHome();
  if (!r.ok) {
    conn.lastError = `Go home failed: ${r.error}`;
    console.error('Go home failed:', r.error);
  }
};

// STOP / PANIC: both buttons just dispatch to the connection store, which
// flips a global modal-open ref. App.vue mounts the actual modals at root.


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
  background: linear-gradient(180deg, #10161e, #0d1218);
  border: 1px solid #27323f;
  border-radius: 8px;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  padding: 0 14px;
  position: relative;
  box-shadow: 0 1px 0 rgba(255,255,255,0.02) inset,
              0 6px 18px rgba(0,0,0,0.4);
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}

.logo-box {
  width: 56px;
  height: 56px;
  background: #06080b;
  border: 1px solid #19212b;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 18px;
}

.toolbar-group {
  display: flex;
  gap: 8px;
  align-items: center;
}

.divider {
  width: 1px;
  height: 36px;
  background: #19212b;
  margin: 0 6px;
}

.tool-btn {
  width: 54px;
  height: 54px;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
  color: #c6d3e0;
}

.tool-btn:hover:not(:disabled) {
  background: #19212b;
  border-color: #27323f;
}
.tool-btn.active {
  background: #10161e;
  border-color: #27323f;
}
.tool-btn:disabled {
  opacity: 0.32;
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
  background: linear-gradient(180deg, #10161e, #0d1218);
  border: 1px solid #27323f;
  border-radius: 6px;
  padding: 6px 0;
  width: 160px;
  z-index: 100;
  margin-top: 6px;
  box-shadow: 0 8px 22px rgba(0,0,0,0.55);
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}

.dropdown-item {
  width: 100%;
  background: transparent;
  border: none;
  color: #c6d3e0;
  padding: 8px 12px;
  text-align: left;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  letter-spacing: 0.5px;
}
.dropdown-item:hover { background: #19212b; color: #ffb020; }

.dropdown-icon-text {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-arrow {
  background: none;
  border: none;
  color: #62717f;
  padding: 0 6px;
  cursor: pointer;
  transition: color 0.15s;
}
.tool-arrow:hover { color: #ffb020; }

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
  background: #0a0d12;
  color: #c6d3e0;
  border: 1px solid #27323f;
  border-radius: 5px;
  padding: 7px 12px;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 12px;
  letter-spacing: 0.4px;
  cursor: pointer;
  outline: none;
  min-width: 140px;
  max-width: 220px;
  transition: border-color 0.15s, background 0.15s;
}

.recordings-select:hover:not(:disabled) {
  background: #10161e;
  border-color: #ffb020;
}
.recordings-select:disabled { opacity: 0.4; cursor: not-allowed; }

.recordings-select option {
  background: #0d1218;
  color: #c6d3e0;
}

/* RT / RP — single segmented amber pill container; the active half lit up
   with a filled gradient + glowing text, the inactive half is muted but
   readable. Hover on either half previews the active color. */
.mode-toggle {
  display: flex;
  align-items: stretch;
  border: 1px solid rgba(255, 176, 32, 0.5);
  border-radius: 6px;
  overflow: hidden;
  background: rgba(20, 14, 6, 0.45);
  box-shadow: 0 0 8px rgba(255, 176, 32, 0.08) inset;
  height: 38px;
}
.mode-toggle .mode-btn {
  width: auto;
  height: auto;
  min-width: 52px;
  padding: 0 12px;
  border: none;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.mode-toggle .mode-btn + .mode-btn {
  border-left: 1px solid rgba(255, 176, 32, 0.35);
}
.mode-toggle .mode-btn:hover:not(:disabled):not(.active) {
  background: rgba(255, 176, 32, 0.07);
}
.mode-toggle .mode-btn:hover:not(:disabled):not(.active) .mode-label {
  color: #ffb020;
}
.mode-toggle .mode-btn.active {
  background: linear-gradient(180deg, #3a2810, #1a1106);
  box-shadow: 0 0 12px rgba(255, 176, 32, 0.28) inset;
}
.mode-label {
  font-size: 12px;
  font-weight: 800;
  color: #997040;
  letter-spacing: 1.5px;
  transition: color 0.15s, text-shadow 0.15s;
}
.mode-toggle .mode-btn.active .mode-label {
  color: #ffb020;
  text-shadow: 0 0 8px rgba(255, 176, 32, 0.7);
}
.mode-toggle .mode-btn:disabled { opacity: 0.32; cursor: not-allowed; }

/* TELE — green-phosphor: idle = colored outline, running = filled +
   pulsing glow. Matches the HOME / STOP pattern (border + label
   color + hover box-shadow). */
.teleop-btn {
  background: rgba(8, 36, 16, 0.4);
  border: 1px solid rgba(105, 209, 128, 0.45);
  transition: all 0.15s;
}
.teleop-btn:hover:not(:disabled) {
  border-color: rgba(105, 209, 128, 0.9);
  box-shadow: 0 0 14px rgba(105, 209, 128, 0.55);
  background: rgba(10, 48, 20, 0.85);
}
.teleop-btn:disabled {
  border-color: rgba(105, 209, 128, 0.18);
  background: transparent;
}
.teleop-btn.active {
  background: linear-gradient(180deg, #0a4a1c, #062810);
  border-color: #69d180;
  box-shadow: 0 0 18px rgba(105, 209, 128, 0.55),
              0 0 0 1px rgba(105, 209, 128, 0.3) inset;
}
.teleop-label {
  font-size: 12px;
  font-weight: 800;
  color: #69d180;
  letter-spacing: 1.5px;
  text-shadow: 0 0 6px rgba(105, 209, 128, 0.5);
  transition: color 0.15s, text-shadow 0.15s;
}
.teleop-label.running {
  color: #88e8a0;
  text-shadow: 0 0 10px rgba(105, 209, 128, 0.85);
  animation: tele-pulse 1.6s ease-in-out infinite;
}
.teleop-btn:disabled .teleop-label {
  color: #62717f;
  text-shadow: none;
}
@keyframes tele-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.72; }
}

/* STOP — Pi-style diagonal red stripes + phosphor glow. */
/* HOME — calm cyan utility button; routes through teleop_quest's 'h' key
   while teleop is up so it doesn't race the active command stream. */
.home-btn {
  background: rgba(8, 28, 36, 0.55);
  border: 1px solid rgba(96, 184, 208, 0.5);
  transition: all 0.15s;
}
.home-btn:hover:not(:disabled) {
  border-color: rgba(96, 184, 208, 0.9);
  box-shadow: 0 0 14px rgba(96, 184, 208, 0.55);
  background: rgba(10, 36, 48, 0.85);
}
.home-btn:disabled {
  border-color: rgba(96, 184, 208, 0.18);
  background: transparent;
}
.home-label {
  font-size: 12px;
  font-weight: 800;
  color: #80d0e8;
  letter-spacing: 1.5px;
  text-shadow: 0 0 6px rgba(96, 184, 208, 0.55);
}
.home-btn:disabled .home-label {
  color: #62717f;
  text-shadow: none;
}

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