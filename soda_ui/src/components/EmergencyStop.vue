<template>
  <!-- Embedded at the far-right end of the TopBar (after StatusRail). Fires on
       pointerdown (before mouseup) for the lowest possible latency — single
       press, no modal, no hold. The action is fully recoverable (relaunch from
       the LauncherCard), so a single deliberate click is the right trade-off;
       mis-click protection comes from the gap separating it from the other
       toolbar buttons + the distinct red-octagon hazard look, not an extra
       confirmation step (which would defeat the point of an e-stop). -->
  <button
    class="estop"
    :class="`estop-${state}`"
    type="button"
    @pointerdown.prevent="fire"
    :title="title"
    aria-label="Emergency stop — instant SIGKILL of all robot processes"
  >
    <span class="estop-octagon">
      <span class="estop-text">
        <span v-if="state === 'firing'">KILL…</span>
        <span v-else-if="state === 'done'">DOWN</span>
        <span v-else-if="state === 'err'">ERR</span>
        <span v-else>E-STOP</span>
      </span>
    </span>
  </button>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue';
import { useConnectionStore } from '@/stores/connection';

const conn = useConnectionStore();

// idle → firing (request in flight) → done | err (flash ~1.5s) → idle
const state = ref('idle');
let resetTimer = null;

const title = computed(() =>
  conn.launcher === 'up'
    ? 'EMERGENCY STOP — instant SIGKILL of all robot processes (this UI survives)'
    : 'Launcher unreachable — e-stop needs `python -m soda_launcher` on the robot host',
);

async function fire() {
  if (state.value === 'firing') return; // ignore re-presses while in flight
  state.value = 'firing';
  if (resetTimer) { clearTimeout(resetTimer); resetTimer = null; }

  // Never let the button get stuck on "KILL…": any thrown error (e.g. the
  // store call rejecting, or a transient undefined during a hot reload) must
  // still land us on a terminal state. The finally always schedules the reset.
  try {
    const r = await conn.estop();
    if (r && r.ok) {
      state.value = 'done';
    } else {
      state.value = 'err';
      conn.lastError = `E-STOP failed: ${r?.error ?? 'unknown error'}`;
    }
  } catch (e) {
    state.value = 'err';
    conn.lastError = `E-STOP failed: ${String(e)}`;
  } finally {
    resetTimer = setTimeout(() => { state.value = 'idle'; }, 1500);
  }
}

onUnmounted(() => { if (resetTimer) clearTimeout(resetTimer); });
</script>

<style scoped>
/* Embedded inline at the far-right of the TopBar. The left margin sets it
   apart from StatusRail so it doesn't read as just another status pill. */
.estop {
  position: relative;
  flex-shrink: 0;
  width: 56px;
  height: 56px;
  margin-left: 12px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  outline: none;
  user-select: none;
  -webkit-touch-callout: none;
  -webkit-tap-highlight-color: transparent;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.5));
  animation: estop-pulse 2.4s ease-in-out infinite;
}

/* Red octagon (stop-sign silhouette) with a yellow hazard rim. */
.estop-octagon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  clip-path: polygon(
    30% 0%, 70% 0%, 100% 30%, 100% 70%,
    70% 100%, 30% 100%, 0% 70%, 0% 30%
  );
  background:
    radial-gradient(circle at 38% 30%, #ff5a4a, #c01608 70%, #7a0d04 100%);
  border: 3px solid #ffd060; /* visually via box-shadow ring below */
  box-shadow:
    0 0 0 3px #1a0606 inset,
    0 0 0 2px rgba(255, 208, 96, 0.85);
  transition: transform 0.08s ease, background 0.15s ease, box-shadow 0.15s ease;
}

.estop-text {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-weight: 900;
  font-size: 9px;
  letter-spacing: 0.3px;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.7), 0 0 6px rgba(255, 120, 100, 0.6);
  line-height: 1;
}

/* Hover: brighten + grow the hazard ring (no animation distraction). */
.estop:hover .estop-octagon {
  background:
    radial-gradient(circle at 38% 30%, #ff6e5e, #d81808 70%, #8a0f05 100%);
  box-shadow:
    0 0 0 3px #1a0606 inset,
    0 0 0 3px rgba(255, 208, 96, 1),
    0 0 18px rgba(255, 60, 40, 0.8);
}
.estop:active .estop-octagon {
  transform: scale(0.93);
}

/* Firing — clamp the pulse, switch to an urgent shake while the request is in
   flight (sub-50ms on localhost, so usually a brief flash). */
.estop-firing { animation: none; }
.estop-firing .estop-octagon {
  background: radial-gradient(circle at 38% 30%, #ffb020, #e07010 70%, #a04808 100%);
  box-shadow: 0 0 0 3px #1a0606 inset, 0 0 0 3px #ffd060, 0 0 22px rgba(255, 160, 32, 0.9);
  animation: estop-shake 0.14s ease-in-out infinite;
}

/* Done — green confirm flash, then auto-resets to idle. */
.estop-done { animation: none; }
.estop-done .estop-octagon {
  background: radial-gradient(circle at 38% 30%, #69d180, #2a8a44 70%, #14552a 100%);
  box-shadow: 0 0 0 3px #06140a inset, 0 0 0 2px rgba(105, 209, 128, 0.9), 0 0 18px rgba(105, 209, 128, 0.7);
}
.estop-done .estop-text { text-shadow: 0 1px 2px rgba(0, 0, 0, 0.7); }

/* Error — keep it red but stop pulsing so the ERR label reads clearly. */
.estop-err { animation: none; }
.estop-err .estop-octagon {
  box-shadow: 0 0 0 3px #1a0606 inset, 0 0 0 3px #ff4438, 0 0 18px rgba(255, 68, 56, 0.85);
}

@keyframes estop-pulse {
  0%, 100% { filter: drop-shadow(0 4px 10px rgba(0, 0, 0, 0.6)) drop-shadow(0 0 4px rgba(255, 48, 48, 0.25)); }
  50%      { filter: drop-shadow(0 4px 10px rgba(0, 0, 0, 0.6)) drop-shadow(0 0 14px rgba(255, 48, 48, 0.55)); }
}
@keyframes estop-shake {
  0%, 100% { transform: translateX(0); }
  25%      { transform: translateX(-1.5px); }
  75%      { transform: translateX(1.5px); }
}
</style>
