<template>
  <Transition name="tb-slide">
    <button
      v-if="visible"
      class="tb-banner"
      title="Click to re-open the teleop overlay"
      @click="reopen"
    >
      <span class="tb-led" :class="{ 'tb-led-rec': recording }" />
      <span class="tb-label">TELEOP ACTIVE</span>
      <span class="tb-status">{{ conn.teleopStatus || '—' }}</span>
      <span class="tb-hint">click to re-open overlay</span>
    </button>
  </Transition>
</template>

<script setup>
import { computed } from 'vue';
import { useConnectionStore } from '@/stores/connection';
const conn = useConnectionStore();

const visible = computed(
  () => conn.teleopRunning && conn.teleopOverlayDismissed && !conn.teleopClosed
);
const recording = computed(() => (conn.teleopStatus || '').toUpperCase().includes('REC'));
function reopen() { conn.teleopOverlayDismissed = false; }
</script>

<style scoped>
.tb-banner {
  position: absolute;
  top: 102px;
  left: 1.5rem; right: 1.5rem;
  z-index: 160;
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px;
  background: linear-gradient(90deg, #0a1812, #1a1106);
  border: 1px solid #ffb020;
  border-radius: 6px;
  box-shadow: 0 0 24px rgba(255, 176, 32, 0.3),
              0 1px 0 rgba(255, 255, 255, 0.02) inset;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 18px;
  color: #ffb020;
  cursor: pointer;
  text-align: left;
  transition: box-shadow 0.18s ease, transform 0.18s ease;
}
.tb-banner:hover {
  box-shadow: 0 0 36px rgba(255, 176, 32, 0.55);
  transform: translateY(-1px);
}
.tb-led {
  width: 14px; height: 14px; border-radius: 50%;
  background: #ffb020;
  box-shadow: 0 0 10px #ffb020, 0 0 2px #fff inset;
  flex-shrink: 0;
  animation: tb-blink 1.0s steps(2, end) infinite;
}
.tb-led-rec {
  background: #ff3030;
  box-shadow: 0 0 12px #ff3030, 0 0 2px #fff inset;
  animation: tb-blink 0.55s steps(2, end) infinite;
}
.tb-label { font-weight: 800; letter-spacing: 2px; }
.tb-status {
  font-size: 16.5px; letter-spacing: 1px; color: #c69a4a;
  padding: 2px 8px; border: 1px solid #5a4214; border-radius: 2px;
  background: #06080b;
}
.tb-hint {
  margin-left: auto; font-size: 15.8px; color: #c69a4a; letter-spacing: 0.4px;
}

@keyframes tb-blink { 50% { opacity: 0.4; } }

.tb-slide-enter-active, .tb-slide-leave-active { transition: all 0.22s ease; }
.tb-slide-enter-from, .tb-slide-leave-to { opacity: 0; transform: translateY(-12px); }
</style>
