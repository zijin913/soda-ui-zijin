<template>
  <div class="jlb" :title="hoverText">
    <div class="track">
      <!-- stop zones at the limits (10° each end by default) -->
      <div class="stop top" :style="{ height: stopPct + '%' }" />
      <div class="stop bot" :style="{ height: stopPct + '%' }" />
      <!-- current position marker -->
      <div class="marker" :class="`m-${markerColor}`" :style="{ bottom: positionPct + '%' }" />
    </div>
    <div class="lab">{{ label }}</div>
    <div class="val num" :class="`v-${markerColor}`">{{ valDisplay }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  /** Current joint angle in radians. */
  angle:  { type: Number, default: 0 },
  /** Lower limit in radians. */
  lower:  { type: Number, default: -3.14 },
  /** Upper limit in radians. */
  upper:  { type: Number, default: 3.14 },
  /** Stop-zone width in degrees (red band at each end). */
  stopDeg:  { type: Number, default: 10 },
  /** Amber-zone width in degrees (amber when clearance is between stop and warn). */
  warnDeg:  { type: Number, default: 20 },
  /** Short label below the bar (e.g. "J1" or "shoulder_pan"). */
  label:    { type: String, default: '' },
});

const RAD2DEG = 180 / Math.PI;

const angleDeg = computed(() => props.angle * RAD2DEG);
const lowerDeg = computed(() => props.lower * RAD2DEG);
const upperDeg = computed(() => props.upper * RAD2DEG);
const rangeDeg = computed(() => Math.max(0.001, upperDeg.value - lowerDeg.value));

// Marker position as % from bottom of the track (0 = at lower, 100 = at upper).
const positionPct = computed(() => {
  const p = (angleDeg.value - lowerDeg.value) / rangeDeg.value;
  return Math.max(0, Math.min(100, p * 100));
});

// Stop zones as % of the track height.
const stopPct = computed(() => Math.min(40, (props.stopDeg / rangeDeg.value) * 100));

// Clearance to nearest limit in degrees.
const clearanceDeg = computed(() => Math.min(
  angleDeg.value - lowerDeg.value,
  upperDeg.value - angleDeg.value,
));

const markerColor = computed(() => {
  if (clearanceDeg.value <= props.stopDeg) return 'red';
  if (clearanceDeg.value <= props.warnDeg) return 'amber';
  return 'grn';
});

const valDisplay = computed(() => {
  const d = angleDeg.value;
  return Math.abs(d) >= 100 ? d.toFixed(0) : d.toFixed(1);
});

const hoverText = computed(() =>
  `${props.label}: ${props.angle.toFixed(3)} rad (${angleDeg.value.toFixed(1)}°)\n`
  + `limits [${lowerDeg.value.toFixed(0)}°, ${upperDeg.value.toFixed(0)}°]\n`
  + `clearance ${clearanceDeg.value.toFixed(1)}°`,
);
</script>

<style scoped>
.jlb {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  width: 28px;
}
.track {
  position: relative;
  width: 14px;
  height: 56px;
  background: #06080b;
  border: 1px solid #19212b;
  border-radius: 2px;
  overflow: hidden;
}
.stop {
  position: absolute;
  left: 0; right: 0;
  background: rgba(255,68,56,0.18);
  border-color: rgba(255,68,56,0.35);
}
.stop.top { top: 0; border-bottom: 1px dashed rgba(255,68,56,0.45); }
.stop.bot { bottom: 0; border-top: 1px dashed rgba(255,68,56,0.45); }

/* Position marker is a 2px horizontal bar centered on the angle's position. */
.marker {
  position: absolute;
  left: 1px; right: 1px;
  height: 3px;
  border-radius: 1px;
  transform: translateY(50%);
  transition: bottom 0.12s ease-out, background 0.2s;
}
.m-grn   { background: #36e08a; box-shadow: 0 0 6px #36e08a; }
.m-amber { background: #ffb020; box-shadow: 0 0 6px #ffb020; }
.m-red   { background: #ff4438; box-shadow: 0 0 8px #ff4438; }

.lab {
  font-size: 13.5px;
  color: #62717f;
  letter-spacing: 0.8px;
  text-transform: uppercase;
}
.val {
  font-size: 14.2px;
  color: #c6d3e0;
}
.v-grn   { color: #36e08a; }
.v-amber { color: #ffb020; }
.v-red   { color: #ff4438; }
</style>
