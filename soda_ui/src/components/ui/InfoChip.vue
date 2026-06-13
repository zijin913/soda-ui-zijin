<template>
  <div class="chip" :class="toneClass" :title="title">
    <span class="k">{{ label }}</span>
    <b class="v num"><slot>{{ value }}</slot></b>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '' },
  tone:  { type: String, default: null },   // 'good' | 'warn' | 'bad' | null
  title: { type: String, default: '' },
});

const toneClass = computed(() => props.tone ? `tone-${props.tone}` : '');
</script>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border: 1px solid #19212b;
  border-radius: 4px;
  background: #0a0d12;
  font-size: 11px;
  line-height: 1;
}
.k {
  font-size: 10px;
  letter-spacing: 1.2px;
  color: #62717f;
  text-transform: uppercase;
}
.v {
  color: #c6d3e0;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.tone-good .v { color: #36e08a; }
.tone-warn .v { color: #ffb020; }
.tone-bad  .v { color: #ff4438; }

.tone-warn { border-color: #5a4214; }
.tone-bad  { border-color: #4a1512; }
</style>
