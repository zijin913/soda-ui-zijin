<template>
  <Transition name="hpb-slide">
    <button
      v-if="visible"
      class="hpb-banner"
      title="Click to re-open the host-policy panel"
      @click="conn.reopenHostPolicy"
    >
      <span class="hpb-led" :class="{ active: active }" />
      <span class="hpb-label">POLICY · {{ phaseLabel }}</span>
      <span v-if="status.policy_name" class="hpb-status">{{ status.policy_name }}</span>
      <span v-if="phase === 'running'" class="hpb-status">step {{ status.step ?? 0 }}</span>
      <span class="hpb-hint">click to re-open panel</span>
    </button>
  </Transition>
</template>

<script setup>
import { computed } from 'vue';
import { useConnectionStore } from '@/stores/connection';
const conn = useConnectionStore();

const visible = computed(() => conn.hostPolicyOpen && conn.hostPolicyDismissed);
const status = computed(() => conn.policyStatus || { phase: 'idle' });
const phase = computed(() => status.value.phase || 'idle');
const active = computed(() => conn.policyActive);
const phaseLabel = computed(() => ({
  idle: 'READY', connecting: 'CONNECTING', homing: 'HOMING', probe: 'PROBING',
  running: 'RUNNING', stopped: 'STOPPED', failed: 'FAILED', done: 'DONE',
}[phase.value] || String(phase.value).toUpperCase()));
</script>

<style scoped>
.hpb-banner {
  position: absolute;
  top: 102px; left: 1.5rem; right: 1.5rem;
  z-index: 160;
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px;
  background: linear-gradient(90deg, #1a1106, #160d28);
  border: 1px solid #ffb347;
  border-radius: 6px;
  box-shadow: 0 0 24px rgba(255, 179, 71, 0.3), 0 1px 0 rgba(255, 255, 255, 0.02) inset;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 12px; color: #ffd28a; cursor: pointer; text-align: left;
  transition: box-shadow 0.18s ease, transform 0.18s ease;
}
.hpb-banner:hover { box-shadow: 0 0 36px rgba(255, 179, 71, 0.55); transform: translateY(-1px); }
.hpb-led { width: 14px; height: 14px; border-radius: 50%; background: #5a4214; box-shadow: 0 0 10px rgba(255,179,71,.4); flex-shrink: 0; }
.hpb-led.active { background: #ffb347; box-shadow: 0 0 12px #ffb347, 0 0 2px #fff inset; animation: hpb-blink 1.0s steps(2, end) infinite; }
.hpb-label { font-weight: 800; letter-spacing: 2px; }
.hpb-status { font-size: 11px; letter-spacing: 1px; color: #c69a4a; padding: 2px 8px; border: 1px solid #3a2c14; border-radius: 2px; background: #06080b; }
.hpb-hint { margin-left: auto; font-size: 10.5px; color: #b88a3a; letter-spacing: 0.4px; }

@keyframes hpb-blink { 50% { opacity: 0.4; } }
.hpb-slide-enter-active, .hpb-slide-leave-active { transition: all 0.22s ease; }
.hpb-slide-enter-from, .hpb-slide-leave-to { opacity: 0; transform: translateY(-12px); }
</style>
