<template>
  <Transition name="cb-slide">
    <button
      v-if="visible"
      class="cb-banner"
      title="Click to re-open the calibration panel"
      @click="conn.reopenCalibration"
    >
      <span class="cb-led" :class="{ active: active }" />
      <span class="cb-label">CALIBRATING · {{ (conn.calibTarget || '').toUpperCase() }}</span>
      <span class="cb-status">{{ phaseLabel }}</span>
      <span v-if="phase === 'collecting'" class="cb-status">{{ samples }}/{{ samplesTarget || '?' }}</span>
      <span class="cb-hint">click to re-open panel</span>
    </button>
  </Transition>
</template>

<script setup>
import { computed } from 'vue';
import { useConnectionStore } from '@/stores/connection';
const conn = useConnectionStore();

// Show whenever the calibration session is open but the panel was dismissed.
const visible = computed(() => conn.calibrationOpen && conn.calibrationDismissed);
const status = computed(() => conn.calibStatus || { phase: 'idle' });
const phase = computed(() => status.value.phase || 'idle');
const active = computed(() => conn.calibActive);
const samples = computed(() => status.value.samples_collected || 0);
const samplesTarget = computed(() => status.value.samples_target || 0);
const phaseLabel = computed(() => ({
  idle: 'READY', positioning: 'POSITION', collecting: 'COLLECTING',
  solving: 'SOLVING', done: 'DONE', failed: 'FAILED', cancelled: 'CANCELLED',
}[phase.value] || String(phase.value).toUpperCase()));
</script>

<style scoped>
.cb-banner {
  position: absolute;
  top: 102px;
  left: 1.5rem; right: 1.5rem;
  z-index: 160;
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px;
  background: linear-gradient(90deg, #160d28, #1a1106);
  border: 1px solid #b082ff;
  border-radius: 6px;
  box-shadow: 0 0 24px rgba(176, 130, 255, 0.3),
              0 1px 0 rgba(255, 255, 255, 0.02) inset;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 12px;
  color: #c2a3ff;
  cursor: pointer;
  text-align: left;
  transition: box-shadow 0.18s ease, transform 0.18s ease;
}
.cb-banner:hover {
  box-shadow: 0 0 36px rgba(176, 130, 255, 0.55);
  transform: translateY(-1px);
}
.cb-led {
  width: 14px; height: 14px; border-radius: 50%;
  background: #5a4a7a; box-shadow: 0 0 10px rgba(176,130,255,.4);
  flex-shrink: 0;
}
.cb-led.active {
  background: #b082ff; box-shadow: 0 0 12px #b082ff, 0 0 2px #fff inset;
  animation: cb-blink 1.0s steps(2, end) infinite;
}
.cb-label { font-weight: 800; letter-spacing: 2px; }
.cb-status {
  font-size: 11px; letter-spacing: 1px; color: #9a8cc0;
  padding: 2px 8px; border: 1px solid #3a2c54; border-radius: 2px;
  background: #06080b;
}
.cb-hint { margin-left: auto; font-size: 10.5px; color: #9a8cc0; letter-spacing: 0.4px; }

@keyframes cb-blink { 50% { opacity: 0.4; } }
.cb-slide-enter-active, .cb-slide-leave-active { transition: all 0.22s ease; }
.cb-slide-enter-from, .cb-slide-leave-to { opacity: 0; transform: translateY(-12px); }
</style>
