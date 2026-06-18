<template>
  <!-- Franka-style PROGRAMMING / EXECUTION switch. EXECUTION = normal control
       (policies / teleop run). PROGRAMMING floats both arms (gravity-comp
       freedrive) so they can be hand-guided. Prominent + set apart since it
       changes the robot's whole control mode. -->
  <div class="tm-switch" :class="{ teaching: conn.teachActive }" v-if="conn.backend === 'up'">
    <button
      class="tm-seg tm-exec"
      :class="{ active: !conn.teachActive }"
      :disabled="!conn.teachActive"
      @click="toExecution"
      title="Execution — normal control; policies and teleop can run"
    >
      <span class="tm-dot" />
      EXECUTION
    </button>
    <button
      class="tm-seg tm-prog"
      :class="{ active: conn.teachActive }"
      :disabled="progDisabled"
      @click="toProgramming"
      :title="progTitle"
    >
      <span class="tm-dot" />
      PROGRAMMING
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { useConnectionStore } from '@/stores/connection';

const conn = useConnectionStore();

// Can't float the arms while something else is commanding them.
const progBlocked = computed(
  () => conn.teleopRunning || conn.calibActive || conn.policyActive,
);
const progDisabled = computed(() => !conn.teachActive && progBlocked.value);
const progTitle = computed(() =>
  conn.teleopRunning ? 'Stop teleop first'
    : conn.calibActive ? 'Stop calibration first'
    : conn.policyActive ? 'Stop the policy first'
    : 'Programming — float both arms (gravity-comp) to hand-guide them',
);

function toExecution() {
  if (conn.teachActive) conn.exitTeach();
}
function toProgramming() {
  if (!conn.teachActive && !progBlocked.value) conn.requestTeach();
}
</script>

<style scoped>
.tm-switch {
  display: inline-flex;
  align-items: stretch;
  border: 1px solid #2a3540;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(6, 8, 11, 0.7);
  backdrop-filter: blur(6px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5);
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  user-select: none;
}
/* While teaching, the whole switch glows amber as a persistent reminder. */
.tm-switch.teaching {
  border-color: rgba(255, 176, 32, 0.7);
  box-shadow: 0 0 22px rgba(255, 176, 32, 0.4), 0 6px 20px rgba(0, 0, 0, 0.5);
}

.tm-seg {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 11px 20px;
  border: none;
  background: transparent;
  color: #62717f;
  font-weight: 800;
  letter-spacing: 1.5px;
  font-size: 16px;
  cursor: pointer;
  transition: all 0.15s;
}
.tm-seg + .tm-seg { border-left: 1px solid #2a3540; }
.tm-seg:disabled { cursor: default; }
.tm-seg:not(:disabled):hover { background: rgba(255, 255, 255, 0.04); }

.tm-dot {
  width: 9px; height: 9px; border-radius: 50%;
  background: #3b4654;
  flex-shrink: 0;
}

/* EXECUTION active — green phosphor. */
.tm-exec.active {
  color: #69d180;
  background: linear-gradient(180deg, #0a3a18, #062810);
  text-shadow: 0 0 8px rgba(105, 209, 128, 0.5);
}
.tm-exec.active .tm-dot { background: #69d180; box-shadow: 0 0 8px #69d180; }

/* PROGRAMMING active — amber phosphor, pulsing dot (arms are compliant). */
.tm-prog.active {
  color: #ffb020;
  background: linear-gradient(180deg, #3a2810, #1a1106);
  text-shadow: 0 0 8px rgba(255, 176, 32, 0.6);
}
.tm-prog.active .tm-dot {
  background: #ffb020;
  box-shadow: 0 0 10px #ffb020;
  animation: tm-pulse 1.2s ease-in-out infinite;
}
@keyframes tm-pulse { 50% { opacity: 0.4; } }
</style>
