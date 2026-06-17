<template>
  <div class="big-ind" :class="state === 'go' ? 'go' : 'no'">
    <LedDot :color="ledColor" size="md" :blink="blink" />
    <span class="label"><slot>{{ label }}</slot></span>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import LedDot from './LedDot.vue';

const props = defineProps({
  state: { type: String, default: 'no' },   // 'go' | 'no'
  label: { type: String, default: '' },
  blink: { type: Boolean, default: false },
});

const ledColor = computed(() => props.state === 'go' ? 'grn' : 'red');
</script>

<style scoped>
.big-ind {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 8px 14px;
  border: 1px solid;
  border-radius: 5px;
  font-weight: 700;
  letter-spacing: 1.5px;
  font-size: 19.5px;
  font-variant-numeric: tabular-nums;
}
.go {
  background: #0d2118;
  border-color: #15402a;
  color: #36e08a;
}
.no {
  background: #160708;
  border-color: #4a1512;
  color: #ff4438;
}
.label { line-height: 1; }
</style>
