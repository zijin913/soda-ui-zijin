<template>
  <div class="state" :class="stateClass">
    <LedDot :color="ledColor" :size="size" :blink="blink" />
    <span class="label">{{ label }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import LedDot from './LedDot.vue';

// Default palette mirrors Pi's state machine for the SODA base.
// Pass a custom palette via prop to override.
const DEFAULT_PALETTE = {
  UP: 'grn',
  RUNNING: 'grn',
  STARTING: 'amber',
  STOPPING: 'amber',
  STOPPED: 'amber',
  DOWN: 'red',
  ESTOP: 'red',
  JOG: 'cyan',
};

const props = defineProps({
  state:   { type: String, required: true },
  label:   { type: String, default: '' },
  palette: { type: Object, default: () => ({}) },
  size:    { type: String, default: 'lg' },
  blink:   { type: Boolean, default: false },
});

const upper = computed(() => (props.state || '').toUpperCase());
const ledColor = computed(() => {
  const merged = { ...DEFAULT_PALETTE, ...props.palette };
  return merged[upper.value] ?? null;
});
const stateClass = computed(() => `s-${upper.value.toLowerCase() || 'unknown'}`);
</script>

<style scoped>
.state {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 6px 14px 6px 11px;
  border-radius: 5px;
  border: 1px solid #27323f;
  background: #0a0d12;
  font-weight: 700;
  letter-spacing: 2px;
  font-size: 18px;
}
.label { line-height: 1; }

.s-running, .s-up { color: #36e08a; border-color: #15402a; }
.s-starting, .s-stopping, .s-stopped { color: #ffb020; border-color: #5a4214; }
.s-down, .s-estop { color: #ff4438; border-color: #4a1512; background: #160708;
  box-shadow: 0 0 0 1px #4a1512, 0 0 22px rgba(255,68,56,0.2) inset; }
.s-jog { color: #36cfe0; border-color: #1a4751; }
.s-unknown { color: #62717f; }
</style>
