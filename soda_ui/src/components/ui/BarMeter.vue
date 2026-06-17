<template>
  <div class="bar" :title="title">
    <div class="track">
      <div v-if="stopAt != null" class="stopline" :style="{ bottom: stopPct + '%' }"></div>
      <div class="fill" :class="`f-${fillColor}`" :style="{ height: fillPct + '%' }"></div>
    </div>
    <div class="lab">{{ label }}</div>
    <div class="val num" :class="`v-${fillColor}`">{{ display }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  value:  { type: Number, default: 0 },
  min:    { type: Number, default: 0 },
  max:    { type: Number, default: 100 },
  stopAt: { type: Number, default: null },   // optional red stopline
  label:  { type: String, default: '' },
  title:  { type: String, default: '' },
  decimals: { type: Number, default: 0 },
});

const range = computed(() => Math.max(0.0001, props.max - props.min));
const fillPct = computed(() => Math.max(4, Math.min(100, ((props.value - props.min) / range.value) * 100)));
const stopPct = computed(() => props.stopAt == null ? 0 : Math.min(100, ((props.stopAt - props.min) / range.value) * 100));
const fillColor = computed(() => {
  if (props.stopAt != null && props.value <= props.stopAt) return 'red';
  if (props.value <= props.min + range.value * 0.2) return 'amber';
  return 'grn';
});
const display = computed(() => props.value.toFixed(props.decimals));
</script>

<style scoped>
.bar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  width: 32px;
}
.track {
  position: relative;
  width: 14px;
  height: 60px;
  background: #06080b;
  border: 1px solid #19212b;
  border-radius: 2px;
  overflow: hidden;
}
.fill {
  position: absolute;
  left: 0; right: 0; bottom: 0;
  transition: height 0.15s ease-out, background 0.2s;
}
.f-grn   { background: #36e08a; box-shadow: 0 0 6px rgba(54,224,138,0.4); }
.f-amber { background: #ffb020; box-shadow: 0 0 6px rgba(255,176,32,0.4); }
.f-red   { background: #ff4438; box-shadow: 0 0 6px rgba(255,68,56,0.5); }
.stopline {
  position: absolute;
  left: 0; right: 0; height: 1px;
  background: #ff4438;
  opacity: 0.6;
}
.lab {
  font-size: 13.5px;
  color: #62717f;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.val {
  font-size: 15px;
  color: #c6d3e0;
}
.v-grn   { color: #36e08a; }
.v-amber { color: #ffb020; }
.v-red   { color: #ff4438; }
</style>
