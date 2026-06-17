<template>
  <div class="launcher-overlay phosphor">
    <div class="launcher-card phosphor-vignette">
      <header class="hdr">
        <LedDot :color="conn.launcher === 'up' ? 'grn' : 'red'" size="lg" />
        <span class="hdr-title">LAUNCHER</span>
        <StatePill class="hdr-pill" :state="headerState" :label="headerSub" :size="'md'" />
      </header>

      <!-- Launcher unreachable: show start instructions instead of buttons -->
      <section v-if="conn.launcher !== 'up'" class="instructions">
        <p class="instr-line">Launcher not reachable on <code>{{ conn.launcherUrl }}</code>.</p>
        <p class="instr-line">Start it on the robot host:</p>
        <pre class="instr-cmd">$ cd ~/Projects/soda-bimanual
$ source activate_env.sh
$ python -m soda_launcher</pre>
        <p class="instr-line">The UI will detect it within ~1 s and unlock the controls.</p>
      </section>

      <!-- Launcher up: mode toggle + Launch/Stop + status + logs -->
      <template v-else>
        <section class="mode-row">
          <span class="k">MODE</span>
          <button
            class="mode-btn"
            :class="{ active: selectedMode === 'sim' }"
            :disabled="conn.backend === 'up'"
            @click="selectedMode = 'sim'"
          >SIM</button>
          <button
            class="mode-btn"
            :class="{ active: selectedMode === 'real' }"
            :disabled="conn.backend === 'up'"
            @click="selectedMode = 'real'"
          >REAL</button>
          <span v-if="conn.mode" class="current-mode">running: <b>{{ conn.mode }}</b></span>
        </section>

        <section class="actions">
          <button class="btn-launch" :disabled="!canLaunch" @click="onLaunch">
            <span class="btn-glyph">▶</span> LAUNCH
          </button>
          <!-- The launcher-screen STOP is the operator's "get me out" button —
               go straight to nuclear (instant SIGKILL all), skip the soft stop
               flow. Same instant estop() as the corner E-STOP, just no
               confirmation here either. -->
          <button class="btn-stop" :disabled="!canStop" @click="conn.estop">
            <span class="btn-glyph">■</span> STOP
          </button>
        </section>

        <section class="status-row">
          <div class="stat-cell">
            <LedDot :color="conn.launcher === 'up' ? 'grn' : 'red'" />
            <span class="k">LCH</span>
            <span class="v">{{ conn.launcher }}</span>
          </div>
          <div class="stat-cell">
            <LedDot :color="backendLed" :blink="conn.backend === 'starting' || conn.backend === 'stopping'" />
            <span class="k">BE</span>
            <span class="v">{{ conn.backend }}</span>
          </div>
          <div class="stat-cell">
            <LedDot :color="hwLed" :blink="conn.hw === 'starting'" />
            <span class="k">HW</span>
            <span class="v">{{ conn.hw }}</span>
          </div>
          <InfoChip v-if="conn.uptimeS > 0" label="UPTIME" :value="uptimeFmt" />
          <InfoChip v-if="conn.cpuPct != null" label="CPU" :value="`${conn.cpuPct.toFixed(0)}%`" />
          <InfoChip v-if="conn.ramPct != null" label="RAM" :value="`${conn.ramPct.toFixed(0)}%`" />
        </section>

        <section v-if="conn.hwPid || conn.backendPid" class="pid-row">
          <span v-if="conn.hwPid">hw: pid <b>{{ conn.hwPid }}</b></span>
          <span v-if="conn.backendPid">backend: pid <b>{{ conn.backendPid }}</b></span>
          <span v-if="conn.backendRssMb != null">be-rss: <b>{{ conn.backendRssMb }} MB</b></span>
        </section>

        <section v-if="actionError" class="error-line">⚠ {{ actionError }}</section>
        <section v-if="conn.lastError" class="error-line">last error: {{ conn.lastError }}</section>

        <section class="log-tail">
          <div class="log-hdr">
            <span class="k">recent log</span>
            <span class="log-event">{{ conn.lastEvent }}</span>
          </div>
          <pre class="log-body">{{ logTailText || '(no output yet)' }}</pre>
        </section>
      </template>
    </div>

  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue';
import { useConnectionStore } from '@/stores/connection';
import LedDot from '@/components/ui/LedDot.vue';
import InfoChip from '@/components/ui/InfoChip.vue';
import StatePill from '@/components/ui/StatePill.vue';

const conn = useConnectionStore();
const selectedMode = ref(conn.mode || 'sim');
const actionError = ref(null);

const canLaunch = computed(() =>
  conn.launcher === 'up' && (conn.backend === 'down' || conn.backend === 'unknown'),
);
const canStop = computed(() =>
  conn.launcher === 'up' && (conn.backend === 'up' || conn.hw === 'up'),
);

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

const headerState = computed(() => {
  if (conn.launcher !== 'up') return 'DOWN';
  if (conn.backend === 'up') return 'UP';
  if (conn.backend === 'starting') return 'STARTING';
  if (conn.backend === 'stopping') return 'STOPPING';
  return 'STOPPED';
});
const headerSub = computed(() => {
  if (conn.launcher !== 'up') return 'UNREACHABLE';
  if (conn.backend === 'up') return 'OPERATIONAL';
  if (conn.backend === 'starting') return 'LAUNCHING';
  if (conn.backend === 'stopping') return 'STOPPING';
  return 'READY';
});

const uptimeFmt = computed(() => {
  const s = conn.uptimeS || 0;
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
});

const logTailText = computed(() => {
  const lines = [...conn.backendLogs.slice(-5), ...conn.hwLogs.slice(-5)];
  return lines.slice(-7).join('\n');
});

async function onLaunch() {
  actionError.value = null;
  const r = await conn.launch(selectedMode.value);
  if (!r.ok) actionError.value = r.error || 'launch failed';
}

// STOP: handled globally via conn.openStopConfirm() / conn.confirmStop().
// Modal is mounted in App.vue so it stacks correctly above this card.

onMounted(() => { conn.startLogTail(); });
onUnmounted(() => { conn.stopLogTail(); });
</script>

<style scoped>
.launcher-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 200;
  /* phosphor class on root provides font/color tokens */
}
.launcher-card {
  pointer-events: auto;
  width: min(860px, 94vw);
  background: linear-gradient(180deg, #10161e, #0d1218);
  border: 1px solid #27323f;
  border-radius: 12px;
  box-shadow: 0 1px 0 rgba(255,255,255,0.02) inset,
              0 22px 60px rgba(0,0,0,0.7);
  padding: 30px 36px;
  font-size: 22.5px;
  line-height: 1.55;
  color: #c6d3e0;
  background-image:
    linear-gradient(180deg, #10161e, #0d1218),
    linear-gradient(#19212b 1px, transparent 1px),
    linear-gradient(90deg, #19212b 1px, transparent 1px);
  background-size: auto, 24px 24px, 24px 24px;
  background-blend-mode: normal, overlay, overlay;
}
.hdr {
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid #19212b;
  padding-bottom: 12px;
  margin-bottom: 14px;
}
.hdr-title {
  font-size: 25.5px;
  font-weight: 700;
  letter-spacing: 3px;
}
.hdr-pill { margin-left: auto; }

.instructions { font-size: 18.8px; }
.instr-line   { margin: 6px 0; }
.instr-cmd {
  background: #06080b;
  border: 1px solid #19212b;
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 18px;
  color: #ffb020;
  margin: 8px 0;
  white-space: pre;
}

.mode-row { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; }
.mode-btn {
  font: inherit;
  font-size: 21px;
  font-weight: 700;
  letter-spacing: 1.4px;
  padding: 10px 24px;
  border: 1px solid #27323f;
  background: #0a0d12;
  color: #c6d3e0;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s;
}
.mode-btn:hover:not(:disabled) { background: #19212b; }
.mode-btn.active {
  border-color: #ffb020;
  color: #ffb020;
  background: #221808;
  box-shadow: 0 0 12px rgba(255,176,32,0.25), 0 0 0 1px rgba(255,176,32,0.4) inset;
}
.mode-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.current-mode {
  margin-left: auto;
  font-size: 16.5px;
  color: #62717f;
}
.current-mode b { color: #c6d3e0; }

.actions { display: flex; gap: 12px; margin-bottom: 14px; }
.btn-launch, .btn-stop {
  flex: 1;
  font: inherit;
  font-size: 27px;
  font-weight: 700;
  letter-spacing: 2.2px;
  padding: 22px 18px;
  border: 1px solid;
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.15s;
  text-shadow: 0 0 6px currentColor;
}
.btn-launch {
  background: #15402a;
  border-color: #36e08a;
  color: #36e08a;
}
.btn-launch:hover:not(:disabled) {
  box-shadow: 0 0 18px rgba(54,224,138,0.5);
  background: #1b5237;
}
.btn-stop {
  border-color: #ff4438;
  color: #ff4438;
  background-image:
    repeating-linear-gradient(45deg,
      #4a1512 0px, #4a1512 5px,
      #2a0a09 5px, #2a0a09 11px);
}
.btn-stop:hover:not(:disabled) {
  box-shadow: 0 0 18px rgba(255,68,56,0.55);
}
.btn-launch:disabled, .btn-stop:disabled {
  opacity: 0.32; cursor: not-allowed;
  box-shadow: none; text-shadow: none;
}
.btn-glyph { margin-right: 4px; }

.status-row {
  display: flex; flex-wrap: wrap; gap: 8px;
  margin-bottom: 8px;
  align-items: center;
}
.stat-cell {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 16.5px;
}
.stat-cell .k {
  font-size: 15px; color: #62717f;
  text-transform: uppercase; letter-spacing: 1.2px;
}
.stat-cell .v { color: #c6d3e0; font-variant-numeric: tabular-nums; }

.pid-row {
  display: flex; gap: 14px;
  font-size: 16.5px; color: #62717f;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.pid-row b { color: #c6d3e0; font-variant-numeric: tabular-nums; }

.error-line {
  font-size: 17.2px; color: #ff4438;
  background: #2a0a09; border-left: 2px solid #ff4438;
  padding: 6px 8px; margin: 4px 0;
  border-radius: 2px;
}

.log-tail { margin-top: 10px; border-top: 1px solid #19212b; padding-top: 10px; }
.log-hdr {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 15px; text-transform: uppercase; letter-spacing: 1.4px;
  color: #62717f;
  margin-bottom: 4px;
}
.log-event { color: #ffb020; text-transform: none; letter-spacing: 0.4px; }
.log-body {
  background: #06080b;
  border: 1px solid #19212b;
  border-radius: 4px;
  padding: 10px 12px; margin: 0;
  font-size: 18.8px;
  color: #62717f;
  max-height: 220px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
</style>
