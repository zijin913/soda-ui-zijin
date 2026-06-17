<template>
  <div class="clear-row phosphor">
    <div v-for="arm in armsToShow" :key="arm.side" class="arm">
      <div class="arm-hdr">
        <span class="arm-label">{{ arm.side.toUpperCase() }}</span>
        <span v-if="anyRed(arm.bars)" class="arm-alert">⚠ NEAR LIMIT</span>
      </div>
      <div class="bar-row">
        <JointLimitBar
          v-for="(bar, idx) in arm.bars"
          :key="bar.id ?? idx"
          :angle="bar.angle"
          :lower="bar.lower"
          :upper="bar.upper"
          :label="bar.label"
        />
        <div v-if="arm.bars.length === 0" class="empty">
          <span class="empty-msg">waiting for joint data…</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import JointLimitBar from '@/components/ui/JointLimitBar.vue';

const props = defineProps({
  /** chartDataHistory from App.vue: `{ left: { id: { angle:[...], ... } }, right: ... }` */
  history:    { type: Object, default: () => ({ left: {}, right: {} }) },
  /** jointNames from App.vue: `{ id: "left_joint_1", ... }` (keyed by backend joint id) */
  jointNames: { type: Object, default: () => ({}) },
  /** jointLimits emitted by RobotViewport: `{ urdf_joint_name: { lower, upper } }`. */
  jointLimits: { type: Object, default: () => ({}) },
  /** Whether to show right arm too. */
  dualMode:   { type: Boolean, default: false },
});

// Resolve URDF limits for a backend joint id by name lookup. Falls back to a
// generous ±π range so the bar still renders if the URDF wasn't loaded yet.
function limitsFor(id) {
  const name = props.jointNames[id];
  const lim = name ? props.jointLimits[name] : null;
  return lim ?? { lower: -Math.PI, upper: Math.PI };
}

function shortLabel(id) {
  const name = props.jointNames[id];
  if (!name) return `J${id}`;
  // "left_joint_1" → "J1", "shoulder_pan" → "shoulder"
  const m = name.match(/joint[_-]?(\d+)/i);
  if (m) return `J${m[1]}`;
  return name.length > 6 ? name.slice(0, 6) : name;
}

function armBars(side) {
  const bucket = props.history?.[side] ?? {};
  return Object.entries(bucket)
    .map(([id, data]) => ({
      id,
      angle: data.angle?.length ? data.angle[data.angle.length - 1] : 0,
      label: shortLabel(id),
      ...limitsFor(id),
    }))
    // Sort by numeric id when possible so J0..J5 line up consistently.
    .sort((a, b) => (Number(a.id) || 0) - (Number(b.id) || 0));
}

const armsToShow = computed(() => {
  const arms = [{ side: 'left', bars: armBars('left') }];
  if (props.dualMode) arms.push({ side: 'right', bars: armBars('right') });
  return arms;
});

function anyRed(bars) {
  const RAD2DEG = 180 / Math.PI;
  return bars.some((b) => {
    const a = b.angle * RAD2DEG;
    const l = b.lower * RAD2DEG;
    const u = b.upper * RAD2DEG;
    return Math.min(a - l, u - a) <= 10;
  });
}
</script>

<style scoped>
.clear-row {
  display: flex;
  align-items: stretch;
  gap: 18px;
  padding: 8px 14px;
  background: linear-gradient(180deg, #0d1218, #0a0e13);
  border: 1px solid #19212b;
  border-radius: 6px;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.arm {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 0 8px;
}
.arm + .arm { border-left: 1px solid #19212b; }
.arm-hdr {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 15px;
  letter-spacing: 1.6px;
  color: #62717f;
  text-transform: uppercase;
  min-height: 12px;
}
.arm-label { color: #c6d3e0; font-weight: 700; }
.arm-alert {
  color: #ff4438;
  font-weight: 700;
  letter-spacing: 1.2px;
  animation: alert-blink 1s steps(2,end) infinite;
}
@keyframes alert-blink { 50% { opacity: 0.4; } }

.bar-row {
  display: flex;
  gap: 6px;
  align-items: flex-end;
  min-height: 80px;
}
.empty {
  display: flex;
  align-items: center;
  padding: 0 8px;
}
.empty-msg {
  font-size: 15px;
  color: #62717f;
  letter-spacing: 1px;
}
</style>
