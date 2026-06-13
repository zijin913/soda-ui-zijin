<template>
  <div class="seg" :title="title">
    <i v-for="i in 3" :key="i" :class="[{ lit: i <= level }, lit && i <= level ? `c-${color}` : '']"></i>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  level: { type: Number, default: 0 },   // 0..3 segments lit
  color: { type: String, default: 'grn' }, // grn | amber | red
  title: { type: String, default: '' },
});

const lit = computed(() => props.level > 0);
</script>

<style scoped>
.seg {
  display: inline-flex;
  gap: 2px;
  align-items: flex-end;
  height: 14px;
}
.seg i {
  width: 5px;
  background: #3b4654;
  border-radius: 1px;
  opacity: 0.5;
  display: block;
}
.seg i:nth-child(1) { height: 6px; }
.seg i:nth-child(2) { height: 10px; }
.seg i:nth-child(3) { height: 14px; }
.seg i.lit { opacity: 1; }
.c-grn   { background: #36e08a; box-shadow: 0 0 4px #36e08a; }
.c-amber { background: #ffb020; box-shadow: 0 0 4px #ffb020; }
.c-red   { background: #ff4438; box-shadow: 0 0 4px #ff4438; }
</style>
