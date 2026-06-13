<template>
  <span class="led" :class="[colorClass, sizeClass, { blink }]" :title="title"></span>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  color: { type: String, default: null },  // 'grn' | 'amber' | 'red' | 'cyan' | 'mag' | null (dim)
  size:  { type: String, default: 'md' },  // 'sm' | 'md' | 'lg'
  blink: { type: Boolean, default: false },
  title: { type: String, default: '' },
});

const colorClass = computed(() => props.color ? `on-${props.color}` : '');
const sizeClass  = computed(() => `sz-${props.size}`);
</script>

<style scoped>
.led {
  display: inline-block;
  border-radius: 50%;
  background: #3b4654;
  box-shadow: 0 0 0 1px rgba(0,0,0,0.6) inset;
  flex-shrink: 0;
  vertical-align: middle;
}
.sz-sm { width: 8px;  height: 8px; }
.sz-md { width: 10px; height: 10px; }
.sz-lg { width: 13px; height: 13px; }

.on-grn   { background: #36e08a; box-shadow: 0 0 8px #36e08a, 0 0 2px #fff inset; }
.on-amber { background: #ffb020; box-shadow: 0 0 8px #ffb020, 0 0 2px #fff inset; }
.on-red   { background: #ff4438; box-shadow: 0 0 10px #ff4438, 0 0 2px #fff inset; }
.on-cyan  { background: #36cfe0; box-shadow: 0 0 8px #36cfe0, 0 0 2px #fff inset; }
.on-mag   { background: #e85cff; box-shadow: 0 0 8px #e85cff, 0 0 2px #fff inset; }

.blink { animation: led-blink 1s steps(2, end) infinite; }
@keyframes led-blink { 50% { opacity: 0.25; } }
</style>
