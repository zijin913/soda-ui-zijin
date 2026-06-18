<template>
<header class="top-bar">
    <!-- Transient error toast (teleop/home/policy failures) so the reason is
         visible in the operational view, not just on the launcher card. -->
    <div v-if="errToast" class="err-toast" @click="errToast = ''" :title="errToast">
      ⚠ {{ errToast }}
    </div>
    <div class="top-bar-content">
      <!-- Logo -->
      <div class="icon-box logo-box">
        <LogoIcon />
      </div>

      <!-- Center toolbar -->
      <div class="toolbar-group">
        <!-- REPLAY toggle — realtime is the default; click to switch into
             replay (review a recording), click again to return to realtime.
             Lit amber while in replay mode. Disabled until backend is up. -->
        <div class="mode-toggle">
          <button class="tool-btn mode-btn" :class="{ 'active': mode === 'replay' }"
                  :disabled="!isBackendUp"
                  :title="!isBackendUp ? backendDisabledTitle :
                          (mode === 'replay' ? 'Back to realtime' : 'Switch to replay')"
                  @click="setMode(mode === 'replay' ? 'realtime' : 'replay')">
            <span class="mode-label">REPLAY</span>
          </button>
        </div>

        <!-- Teleop (only in realtime mode) — launches scripts/teleop_quest.py
             via the backend. Green-phosphor: matches the in-UI overlay aesthetic
             and signals "live data flowing" (distinct from HOME cyan and
             STOP red). -->
        <button v-if="mode === 'realtime'" class="tool-btn teleop-btn" :class="{ 'active': isTeleopRunning }"
                :disabled="!isBackendUp || isCalibActive || conn.teachActive"
                @click="toggleTeleop"
                :title="!isBackendUp ? backendDisabledTitle :
                        conn.teachActive ? 'Exit programming mode first' :
                        isCalibActive ? 'Calibration in progress' :
                        isTeleopRunning ? 'Stop teleop' : 'Start teleop (recording is asked in the camera window that pops up on the robot host)'">
          <span class="teleop-label" :class="{ 'running': isTeleopRunning }">TELEOP</span>
        </button>

        <!-- CALIBRATE lives in the first camera panel's header now (it's a
             camera task), so it's not in this toolbar. -->

        <!-- HOST POLICY (only in realtime) — opens the policy modal. Shares the
             single command client, so it can't coexist with teleop/calibration. -->
        <button v-if="mode === 'realtime'" class="tool-btn policy-btn" :class="{ 'active': isPolicyActive }"
                :disabled="!isBackendUp || isTeleopRunning || isCalibActive || conn.teachActive"
                @click="conn.openHostPolicy"
                :title="!isBackendUp ? backendDisabledTitle :
                        conn.teachActive ? 'Exit programming mode first' :
                        isTeleopRunning ? 'Stop teleop first' :
                        isCalibActive ? 'Stop calibration first' :
                        'Host a policy (pick policy + params, then run)'">
          <span class="policy-label" :class="{ 'running': isPolicyActive }">POLICY</span>
        </button>

        <!-- HOME — move both arms to home pose. During teleop routes through
             teleop_quest's 'h' key (clears pending target + pauses) so it
             doesn't race teleop's command stream. Otherwise POSTs /robot/home. -->
        <button class="tool-btn home-btn"
                :disabled="!isBackendUp || conn.homing || conn.teachActive"
                @click="onHome"
                :title="!isBackendUp ? backendDisabledTitle :
                        conn.teachActive ? 'Exit programming mode first' :
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
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import LogoIcon from '@/components/icons/LogoIcon.vue';
import CoordinateIcon from '@/components/icons/Coordinate.vue';
import DepthToolIcon from '@/components/icons/DepthToolIcon.vue';
import StatusRail from '@/components/StatusRail.vue';
import EmergencyStop from '@/components/EmergencyStop.vue';
import { useConnectionStore } from '@/stores/connection';

const conn = useConnectionStore();

// Surface backend errors (e.g. teleop "No Quest device found") as a visible
// toast in the operational view — otherwise conn.lastError only shows on the
// launcher card / teleop overlay, so a failed TELE click looks like nothing.
const errToast = ref('');
let _errTimer = null;
watch(() => conn.lastError, (e) => {
  if (!e) return;
  errToast.value = e;
  if (_errTimer) clearTimeout(_errTimer);
  _errTimer = setTimeout(() => { errToast.value = ''; }, 7000);
});
const isBackendUp = computed(() => conn.backend === 'up');
const canStop = computed(() => conn.launcher === 'up' && (conn.backend === 'up' || conn.hw === 'up'));
const backendDisabledTitle = computed(() =>
  conn.launcher === 'up'
    ? 'Backend is down — start it from the Launcher card'
    : 'Launcher not reachable — start `python -m soda_launcher` on the robot host',
);

const emit = defineEmits(['toggleDepth', 'toggleCoordinate', 'teleopToggled', 'modeChanged', 'replayControl']);

const isCoordinateActive = ref(false);
const isDepthActive = ref(false);
// Teleop running state lives in the connection store now (also visible from
// StatusRail). It's polled by the store; we just read it.
const isTeleopRunning = computed(() => conn.teleopRunning);
// Calibration owns the arm exclusively; mirror teleop's button-level interlock.
const isCalibActive = computed(() => conn.calibActive);
const isPolicyActive = computed(() => conn.policyActive);
const recordingFiles = ref([]);
const selectedRecording = ref('');
const mode = ref('realtime');

const toggleCoordinate = () => {
  isCoordinateActive.value = !isCoordinateActive.value;
  emit('toggleCoordinate', isCoordinateActive.value);
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
    } else {
      // Surface the backend's reason (e.g. "No Quest device found … adb devices")
      // instead of a silent flash-and-quit.
      const data = await response.json().catch(() => ({}));
      conn.lastError = data?.error || `Teleop ${isTeleopRunning.value ? 'stop' : 'start'} failed (HTTP ${response.status})`;
    }
  } catch (error) {
    conn.lastError = `Teleop request failed: ${error}`;
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

.err-toast {
  position: absolute;
  top: 100px;
  left: 50%;
  transform: translateX(-50%);
  max-width: 80vw;
  min-width: 420px;
  z-index: 200;
  background: linear-gradient(180deg, #2a0f0f, #1a0a0a);
  border: 2px solid #ff6b5a;
  color: #ffe2dc;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 18px;
  line-height: 1.45;
  font-weight: 600;
  padding: 18px 26px;
  border-radius: 10px;
  box-shadow: 0 10px 36px rgba(0, 0, 0, 0.6), 0 0 22px rgba(255, 107, 90, 0.25);
  cursor: pointer;
  white-space: normal;        /* wrap so the full message is readable */
  text-align: center;
}

.top-bar-content {
  background: linear-gradient(180deg, #10161e, #0d1218);
  border: 1px solid #27323f;
  border-radius: 8px;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  padding: 0 32px;
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
  margin-right: 28px;
}

.toolbar-group {
  display: flex;
  gap: 22px;
  align-items: center;
}

.divider {
  width: 1px;
  height: 36px;
  background: #19212b;
  margin: 0 22px;
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

/* The five labeled action boxes (TELE / CAL / POL / HOME / STOP). Unlike the
   square icon buttons they hold text, so size to content with horizontal
   padding (prevents HOME/labels from spilling past the box) and run a touch
   larger than the 54px icon buttons. */
.teleop-btn,
.calib-btn,
.policy-btn,
.home-btn,
.stop-btn {
  width: auto;
  min-width: 66px;
  height: 58px;
  padding: 0 18px;
}

/* StatusRail sits at the far right of the header. */
.rail-slot {
  margin-left: auto;
  display: flex;
  align-items: center;
  padding-right: 4px;
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
  font-size: 18px;
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
  font-size: 18px;
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
  font-size: 18px;
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

/* CAL — violet phosphor, distinct from teleop green / home cyan. Idle =
   colored outline, active (a session running) = filled + pulsing glow. */
.calib-btn {
  background: rgba(26, 14, 40, 0.45);
  border: 1px solid rgba(176, 130, 255, 0.5);
  transition: all 0.15s;
}
.calib-btn:hover:not(:disabled) {
  border-color: rgba(176, 130, 255, 0.95);
  box-shadow: 0 0 14px rgba(176, 130, 255, 0.55);
  background: rgba(36, 20, 56, 0.85);
}
.calib-btn:disabled {
  border-color: rgba(176, 130, 255, 0.18);
  background: transparent;
}
.calib-btn.active {
  background: linear-gradient(180deg, #2c1850, #150a28);
  border-color: #b082ff;
  box-shadow: 0 0 18px rgba(176, 130, 255, 0.55),
              0 0 0 1px rgba(176, 130, 255, 0.3) inset;
}
.calib-label {
  font-size: 18px;
  font-weight: 800;
  color: #c2a3ff;
  letter-spacing: 1.5px;
  text-shadow: 0 0 6px rgba(176, 130, 255, 0.5);
  transition: color 0.15s, text-shadow 0.15s;
}
.calib-label.running {
  color: #d9c4ff;
  text-shadow: 0 0 10px rgba(176, 130, 255, 0.85);
  animation: tele-pulse 1.6s ease-in-out infinite;
}
.calib-btn:disabled .calib-label {
  color: #62717f;
  text-shadow: none;
}

/* HOST POLICY — amber phosphor, distinct from teleop-green / calib-violet. */
.policy-btn {
  background: rgba(40, 28, 8, 0.45);
  border: 1px solid rgba(255, 179, 71, 0.5);
  transition: all 0.15s;
}
.policy-btn:hover:not(:disabled) {
  border-color: rgba(255, 179, 71, 0.95);
  box-shadow: 0 0 14px rgba(255, 179, 71, 0.55);
  background: rgba(56, 38, 12, 0.85);
}
.policy-btn:disabled { border-color: rgba(255, 179, 71, 0.18); background: transparent; }
.policy-btn.active {
  background: linear-gradient(180deg, #50360e, #281a06);
  border-color: #ffb347;
  box-shadow: 0 0 18px rgba(255, 179, 71, 0.55), 0 0 0 1px rgba(255, 179, 71, 0.3) inset;
}
.policy-label {
  font-size: 18px; font-weight: 800; color: #ffd28a; letter-spacing: 1.5px;
  text-shadow: 0 0 6px rgba(255, 179, 71, 0.5);
  transition: color 0.15s, text-shadow 0.15s;
}
.policy-label.running {
  color: #ffe6c2; text-shadow: 0 0 10px rgba(255, 179, 71, 0.85);
  animation: tele-pulse 1.6s ease-in-out infinite;
}
.policy-btn:disabled .policy-label { color: #62717f; text-shadow: none; }

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
  font-size: 18px;
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
  font-size: 18px;
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
  font-size: 24px;
}
</style>