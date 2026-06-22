<template>
  <!-- Mode switcher — matches RightSidebar panel-block aesthetic.
       EXECUTION = closed-loop control (policies / teleop run).
       PROGRAMMING = gravity-comp freedrive (arms float for hand-guiding). -->
  <div class="mode-panel" :class="{ teaching: conn.teachActive }" v-if="conn.backend === 'up'">
    <div class="mode-header">
      <span class="mode-bullet" />
      Mode
    </div>

    <div class="mode-toggle">
      <button
        class="mode-seg exec"
        :class="{ active: !conn.teachActive }"
        :disabled="!conn.teachActive"
        @click="toExecution"
        title="Execution — normal control; policies and teleop can run"
      >
        <span class="seg-label">EXECUTION</span>
      </button>
      <button
        class="mode-seg prog"
        :class="{ active: conn.teachActive }"
        :disabled="progDisabled"
        @click="toProgramming"
        :title="progTitle"
      >
        <span class="seg-label">PROGRAMMING</span>
      </button>
    </div>

    <div class="mode-status">
      <span class="status-dot" />
      <span class="status-text">
        <template v-if="conn.teachActive">Arms floating — hand-guide</template>
        <template v-else>Closed-loop control active</template>
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useConnectionStore } from "@/stores/connection";

const conn = useConnectionStore();

// Programming barges in even if a policy/teleop is running (they pause and
// resume on Execution). Calibration genuinely conflicts (it also floats arms).
const progBlocked = computed(() => conn.calibActive);
const progDisabled = computed(() => !conn.teachActive && progBlocked.value);
const progTitle = computed(() =>
  conn.calibActive ? "Stop calibration first"
    : (conn.teleopRunning || conn.policyActive)
      ? "Programming — interrupts the running task (it resumes on Execution)"
      : "Programming — float both arms (gravity-comp) to hand-guide them",
);

function toExecution() {
  if (conn.teachActive) conn.exitTeach();
}
function toProgramming() {
  if (!conn.teachActive && !progBlocked.value) conn.requestTeach();
}
</script>

<style scoped>
/* === Panel — visually consistent with RightSidebar.panel-block === */
.mode-panel {
  background: linear-gradient(180deg, #10161e, #0d1218);
  border: 1px solid #27323f;
  border-radius: 8px;
  padding: 14px 16px;
  backdrop-filter: blur(6px);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4);
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  transition: border-color 220ms ease, box-shadow 220ms ease;
}
/* In PROGRAMMING the whole panel glows amber — persistent reminder. */
.mode-panel.teaching {
  border-color: rgba(255, 176, 32, 0.7);
  box-shadow:
    0 0 22px rgba(255, 176, 32, 0.35),
    0 4px 14px rgba(0, 0, 0, 0.4);
}

/* === Header — same font / color tokens as panel-header in sidebar === */
.mode-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 18px;
  letter-spacing: 1.8px;
  text-transform: uppercase;
  color: #c6d3e0;
  padding-bottom: 8px;
  border-bottom: 1px solid #19212b;
  margin-bottom: 12px;
}
.mode-bullet {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #4ade80;
  box-shadow: 0 0 10px rgba(74, 222, 128, 0.6);
  transition: background 220ms ease, box-shadow 220ms ease;
}
.mode-panel.teaching .mode-bullet {
  background: #ffb020;
  box-shadow: 0 0 12px rgba(255, 176, 32, 0.7);
}

/* === Segmented toggle === */
.mode-toggle {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  background: rgba(6, 8, 11, 0.7);
  border: 1px solid #2a3540;
  border-radius: 10px;
  overflow: hidden;
  height: 46px;
}
.mode-seg {
  border: none;
  background: transparent;
  color: #6e7e8e;
  font-family: inherit;
  font-weight: 700;
  font-size: 13px;
  letter-spacing: 1.5px;
  cursor: pointer;
  transition:
    background 220ms ease,
    color 180ms ease,
    box-shadow 180ms ease;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}
.mode-seg + .mode-seg { border-left: 1px solid #2a3540; }

.mode-seg:hover:not(.active):not(:disabled) {
  background: rgba(255, 255, 255, 0.03);
  color: #b6c4d1;
}

.mode-seg:disabled { cursor: default; }

/* Active states — strongly colored, no ambiguity. */
.mode-seg.exec.active {
  background: linear-gradient(180deg, #1f8b4a, #16703a);
  color: #f4fff7;
  text-shadow: 0 1px 0 rgba(0, 0, 0, 0.35);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.12),
    inset 0 -2px 0 rgba(0, 0, 0, 0.4);
}
.mode-seg.prog.active {
  background: linear-gradient(180deg, #d28a14, #a26a08);
  color: #fff8e6;
  text-shadow: 0 1px 0 rgba(0, 0, 0, 0.35);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.16),
    inset 0 -2px 0 rgba(0, 0, 0, 0.45);
}

/* === Status line === */
.mode-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 12px;
  color: #8da0b3;
  letter-spacing: 0.4px;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4ade80;
  box-shadow: 0 0 8px rgba(74, 222, 128, 0.6);
  flex-shrink: 0;
  transition: background 220ms ease, box-shadow 220ms ease;
}
.mode-panel.teaching .status-dot {
  background: #ffb020;
  box-shadow: 0 0 8px rgba(255, 176, 32, 0.7);
  animation: amber-pulse 1.6s ease-in-out infinite;
}
.mode-panel.teaching .status-text {
  color: #ffd685;
}

@keyframes amber-pulse {
  0%, 100% { box-shadow: 0 0 8px rgba(255, 176, 32, 0.45); }
  50%      { box-shadow: 0 0 14px rgba(255, 176, 32, 0.95); }
}
</style>
