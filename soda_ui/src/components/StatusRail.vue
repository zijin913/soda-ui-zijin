<template>
  <div class="status-rail phosphor phosphor-grid">
    <!-- launcher / backend / hw LEDs -->
    <div class="cell" :title="`launcher: ${conn.launcher}`">
      <LedDot :color="launcherLed" />
      <span class="k">LCH</span>
    </div>
    <div class="cell" :title="`backend: ${conn.backend}`">
      <LedDot :color="backendLed" :blink="conn.backend === 'starting' || conn.backend === 'stopping'" />
      <span class="k">BE</span>
    </div>
    <div class="cell" :title="`hardware servers: ${conn.hw}`">
      <LedDot :color="hwLed" :blink="conn.hw === 'starting'" />
      <span class="k">HW</span>
    </div>

    <div class="vsep" />

    <!-- mode + WS fps + RTT -->
    <InfoChip label="MODE" :value="conn.mode ? conn.mode.toUpperCase() : '—'"
              :tone="conn.mode ? 'good' : null" />
    <InfoChip label="WS"
              :value="conn.wsConnected ? `${conn.wsFps} fps` : '·'"
              :tone="conn.wsConnected ? 'good' : 'bad'" />
    <InfoChip v-if="conn.wsLatencyMs != null" label="RTT" :value="`${conn.wsLatencyMs} ms`" />

    <div v-if="hasMetrics" class="vsep" />

    <!-- host metrics -->
    <InfoChip v-if="conn.cpuPct != null" label="CPU" :value="`${conn.cpuPct.toFixed(0)}%`"
              :tone="conn.cpuPct > 85 ? 'warn' : null"
              :title="`Host CPU: ${conn.cpuPct.toFixed(1)}%`" />
    <InfoChip v-if="conn.ramPct != null" label="RAM" :value="`${conn.ramPct.toFixed(0)}%`"
              :tone="conn.ramPct > 85 ? 'warn' : null"
              :title="`Host RAM: ${conn.ramPct.toFixed(1)}%`" />
    <InfoChip v-if="conn.backendRssMb != null" label="BE-MB" :value="conn.backendRssMb.toFixed(0)"
              :title="`Backend RSS: ${conn.backendRssMb} MB`" />

    <div v-if="conn.isOperational || conn.teleopRunning" class="vsep" />

    <!-- uptime + teleop + zero-grav -->
    <InfoChip v-if="conn.isOperational && conn.uptimeS > 0" label="UP" :value="uptime" />

    <!-- Teleop status removed from the rail: the TELEOP button in the toolbar
         already glows while running, so this was a duplicate indicator. -->

    <div v-if="conn.zeroGravityActive" class="cell zg-cell"
         title="zero-gravity is active — arms are free to move">
      <LedDot color="amber" blink />
      <span class="k zg">ZERO-G</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { useConnectionStore } from '@/stores/connection';
import LedDot from '@/components/ui/LedDot.vue';
import InfoChip from '@/components/ui/InfoChip.vue';

const conn = useConnectionStore();

const launcherLed = computed(() => conn.launcher === 'up' ? 'grn' : 'red');
const backendLed = computed(() => {
  if (conn.backend === 'up') return 'grn';
  if (conn.backend === 'starting' || conn.backend === 'stopping') return 'amber';
  return 'red';
});
const hwLed = computed(() => {
  if (conn.hw === 'up') return 'grn';
  if (conn.hw === 'starting') return 'amber';
  return 'red';
});

const hasMetrics = computed(() =>
  conn.cpuPct != null || conn.ramPct != null || conn.backendRssMb != null,
);

const uptime = computed(() => {
  const s = conn.uptimeS || 0;
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
});
</script>

<style scoped>
.status-rail {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background:
    linear-gradient(180deg, #10161e, #0d1218);
  border: 1px solid #27323f;
  border-radius: 8px;
  box-shadow: 0 1px 0 rgba(255,255,255,0.02) inset,
              0 6px 18px rgba(0,0,0,0.4);
  /* phosphor-grid utility provides the hairline overlay */
  background-blend-mode: normal;
}
.cell {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 4px;
  font-size: 16.5px;
}
.vsep {
  width: 1px;
  height: 18px;
  background: #19212b;
  margin: 0 4px;
}
.tele-cell .tele { color: #36e08a; font-weight: 700; }
.zg-cell {
  border: 1px solid #5a4214;
  border-radius: 4px;
  padding: 2px 7px;
  background: rgba(255,176,32,0.06);
  animation: pulse-warn 1.4s ease-in-out infinite;
}
.zg-cell .zg { color: #ffb020; font-weight: 700; }

@keyframes pulse-warn {
  0%, 100% { box-shadow: 0 0 0 rgba(255,176,32,0); }
  50%      { box-shadow: 0 0 14px rgba(255,176,32,0.45); }
}
</style>
