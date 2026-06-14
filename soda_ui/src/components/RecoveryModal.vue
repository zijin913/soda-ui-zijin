<template>
  <Transition name="rm-fade">
    <div v-if="visible" class="rm-backdrop">
      <div class="rm-scanlines" />

      <div class="rm-card phosphor" :class="`rm-phase-${phase}`">
        <!-- ┌── header: phase-specific ────────────────────────────────── -->
        <header class="rm-head">
          <span class="rm-led" :class="`rm-led-${phase}`" />
          <span class="rm-title">{{ headerTitle }}</span>
          <span class="rm-subtitle">{{ headerSubtitle }}</span>
        </header>

        <!-- ── body ─────────────────────────────────────────────────── -->
        <div class="rm-body">

          <!-- ░░░ STARTING (boot log) ░░░ -->
          <div v-if="phase === 'starting'" class="rm-bootlog">
            <div v-for="(step, i) in startingSteps" :key="i"
                 class="rm-log-line"
                 :class="{
                   'rm-log-done': step.state === 'done',
                   'rm-log-active': step.state === 'active',
                   'rm-log-pending': step.state === 'pending',
                 }">
              <span class="rm-log-prompt">&gt;</span>
              <span class="rm-log-text">{{ step.label }}</span>
              <span class="rm-log-status">
                <template v-if="step.state === 'done'">[<span class="rm-check">✓</span>]</template>
                <template v-else-if="step.state === 'active'">[<span class="rm-spin">⟳</span>]</template>
                <template v-else>[ ]</template>
              </span>
            </div>

            <div class="rm-hint-text">PREPARING RECOVERY — ARMS WILL BE FREE TO MOVE IN A MOMENT</div>
          </div>

          <!-- ░░░ ACTIVE (zero-gravity running) ░░░ -->
          <div v-else-if="phase === 'active'">
            <div class="rm-instr">
              <div class="rm-step-num">01</div>
              <div class="rm-step-text">
                <div class="rm-step-title">Push both arms back to <kbd>HOME</kbd> pose</div>
                <div class="rm-step-hint">gravity-compensated — they move freely</div>
              </div>
            </div>

            <div class="rm-instr">
              <div class="rm-step-num">02</div>
              <div class="rm-step-text">
                <div class="rm-step-title">Press <kbd>DONE</kbd> when arms are home</div>
                <div class="rm-step-hint">kills zero-gravity + servers, brings back launcher</div>
              </div>
            </div>

            <div class="rm-meter">
              <span class="rm-meter-led" />
              <span class="rm-meter-label">ZERO-G UPTIME</span>
              <span class="rm-meter-value">{{ uptimeText }}</span>
              <span class="rm-meter-sep">·</span>
              <span class="rm-meter-label">STATE</span>
              <span class="rm-meter-value">FREE-FLOATING</span>
            </div>
          </div>

          <!-- ░░░ FINISHING (shutdown log) ░░░ -->
          <div v-else-if="phase === 'finishing'" class="rm-bootlog">
            <div v-for="(step, i) in finishingSteps" :key="i"
                 class="rm-log-line"
                 :class="{
                   'rm-log-done': step.state === 'done',
                   'rm-log-active': step.state === 'active',
                   'rm-log-pending': step.state === 'pending',
                 }">
              <span class="rm-log-prompt">&gt;</span>
              <span class="rm-log-text">{{ step.label }}</span>
              <span class="rm-log-status">
                <template v-if="step.state === 'done'">[<span class="rm-check">✓</span>]</template>
                <template v-else-if="step.state === 'active'">[<span class="rm-spin">⟳</span>]</template>
                <template v-else>[ ]</template>
              </span>
            </div>

            <div class="rm-hint-text">SHUTTING DOWN — LAUNCHER WILL RETURN SHORTLY</div>
          </div>

          <div v-if="conn.lastError" class="rm-error">! {{ conn.lastError }}</div>
        </div>

        <!-- ── footer (only in active phase) ───────────────────────── -->
        <footer v-if="phase === 'active'" class="rm-foot">
          <button class="rm-btn rm-cancel" @click="onDismiss"
                  title="Keep zero-gravity running, just dismiss the overlay">
            DISMISS OVERLAY
          </button>
          <button class="rm-btn rm-confirm" @click="onFinish">
            DONE — SHUT DOWN
          </button>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue';
import { useConnectionStore } from '@/stores/connection';

const conn = useConnectionStore();
const startedAt = ref(null);
const tick = ref(0);
let tickTimer = null;

// ── STARTING phase: fake-progressed boot log ──────────────────────────
// recover_zerog.py runs ~3-5 seconds. We fake step transitions to give the
// operator visible feedback. Actual completion is signaled by
// conn.zeroGravityActive flipping true (handled by watcher below).
const startingStepLabels = [
  'TERMINATING TELEOP',
  'TERMINATING BACKEND',
  'TERMINATING LAUNCHERS',
  'STARTING ZERO-GRAVITY',
];
// Step durations in ms (0-indexed step transitions).
const STARTING_TIMINGS = [0, 800, 1700, 2600];
const startingActiveIdx = ref(0);
let startingTimer = null;

const startingSteps = computed(() => {
  return startingStepLabels.map((label, i) => ({
    label,
    state:
      i < startingActiveIdx.value ? 'done' :
      i === startingActiveIdx.value ? 'active' : 'pending',
  }));
});

function startBootSequence() {
  startingActiveIdx.value = 0;
  if (startingTimer) clearInterval(startingTimer);
  // Advance every ~900ms but never past the last step (we hold there
  // spinning until conn.zeroGravityActive flips true).
  startingTimer = window.setInterval(() => {
    if (startingActiveIdx.value < startingStepLabels.length - 1) {
      startingActiveIdx.value++;
    }
  }, 900);
}
function stopBootSequence() {
  if (startingTimer) { clearInterval(startingTimer); startingTimer = null; }
}

// ── FINISHING phase: short shutdown log ─────────────────────────────
const finishingStepLabels = [
  'SIGINT ZERO-GRAVITY',
  'RUNNING kill_servers.sh',
  'CLEANING UP',
];
const finishingActiveIdx = ref(0);
let finishingTimer = null;
const finishingSteps = computed(() => {
  return finishingStepLabels.map((label, i) => ({
    label,
    state:
      i < finishingActiveIdx.value ? 'done' :
      i === finishingActiveIdx.value ? 'active' : 'pending',
  }));
});
function startShutdownSequence() {
  finishingActiveIdx.value = 0;
  if (finishingTimer) clearInterval(finishingTimer);
  finishingTimer = window.setInterval(() => {
    if (finishingActiveIdx.value < finishingStepLabels.length - 1) {
      finishingActiveIdx.value++;
    }
  }, 700);
}
function stopShutdownSequence() {
  if (finishingTimer) { clearInterval(finishingTimer); finishingTimer = null; }
}

// ── phase computation ───────────────────────────────────────────────
const phase = computed(() => {
  if (conn.recoveryFinishing) return 'finishing';
  if (conn.zeroGravityActive) return 'active';
  if (conn.recoveryStarting) return 'starting';
  return 'idle';
});

const visible = computed(() => {
  if (phase.value === 'idle') return false;
  if (phase.value === 'active' && conn.recoveryModalDismissed) return false;
  return true;
});

const headerTitle = computed(() => ({
  starting: 'INITIATING ZERO-GRAVITY',
  active: 'ZERO-GRAVITY ACTIVE',
  finishing: 'SHUTTING DOWN',
  idle: '',
}[phase.value]));

const headerSubtitle = computed(() => ({
  starting: 'PREPARING ARMS',
  active: 'ARMS ARE FREE TO MOVE',
  finishing: 'RETURNING TO IDLE',
  idle: '',
}[phase.value]));

// ── lifecycle: drive sub-animations based on phase ────────────────
watch(phase, (p, prev) => {
  if (p === 'starting') startBootSequence();
  else stopBootSequence();

  if (p === 'finishing') startShutdownSequence();
  else stopShutdownSequence();

  if (p === 'active' && prev !== 'active') {
    // Just entered active: clear starting flag, reset uptime, reset dismiss.
    conn.endRecoveryStarting();
    conn.recoveryModalDismissed = false;
    startedAt.value = Date.now();
    if (!tickTimer) tickTimer = window.setInterval(() => { tick.value++; }, 500);
  }
  if (p !== 'active') {
    startedAt.value = null;
    if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
  }

  if (p === 'idle') conn.recoveryModalDismissed = false;
}, { immediate: true });

// Auto-clear FINISHING when zero-g is actually gone (we waited for the
// kill_servers.sh launcher call to complete, so all flags can drop). Give
// the user a short beat to see the last [⟳] tick to [✓].
watch(() => conn.zeroGravityActive, (active) => {
  if (!active && conn.recoveryFinishing) {
    // Advance shutdown log to the last step (CLEANING UP done) then close.
    finishingActiveIdx.value = finishingStepLabels.length;
    window.setTimeout(() => { conn.recoveryFinishing = false; }, 900);
  }
});

// Safety: if we're stuck in FINISHING for too long without zero-g flipping
// off (e.g. launcher call failed silently), let the user escape after 15s
// instead of being trapped forever. Also handle the edge case where zero-g
// was already gone before FINISHING was triggered.
let finishingSafetyTimer = null;
watch(() => conn.recoveryFinishing, (finishing) => {
  if (finishingSafetyTimer) { clearTimeout(finishingSafetyTimer); finishingSafetyTimer = null; }
  if (finishing) {
    // Edge case: zero-g already gone when DONE was clicked — the
    // zeroGravityActive watcher won't fire, so trigger close ourselves.
    if (!conn.zeroGravityActive) {
      finishingActiveIdx.value = finishingStepLabels.length;
      window.setTimeout(() => { conn.recoveryFinishing = false; }, 900);
      return;
    }
    finishingSafetyTimer = window.setTimeout(() => {
      // Bail out — finishing has been stuck for 15s. Hide the modal and
      // surface an error so the user knows something went wrong.
      if (conn.recoveryFinishing) {
        conn.lastError = 'Recovery finishing timed out; check launcher logs.';
        conn.recoveryFinishing = false;
      }
    }, 15_000);
  }
});

onUnmounted(() => {
  stopBootSequence();
  stopShutdownSequence();
  if (tickTimer) clearInterval(tickTimer);
});

const uptimeText = computed(() => {
  tick.value;
  if (!startedAt.value) return '00:00';
  const s = Math.floor((Date.now() - startedAt.value) / 1000);
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${mm}:${ss}`;
});

// ── actions ─────────────────────────────────────────────────────
async function onFinish() {
  conn.recoveryFinishing = true;
  const r = await conn.finishRecovery();
  if (!r.ok) {
    conn.lastError = `Recovery finish failed: ${r.error}`;
    conn.recoveryFinishing = false;
  }
  // Else: launcher kills zero-g, next poll flips zeroGravityActive=false,
  // phase becomes 'idle', modal hides.
}

function onDismiss() {
  conn.recoveryModalDismissed = true;
}
</script>

<style scoped>
.rm-backdrop {
  position: fixed; inset: 0; z-index: 9999;
  background: radial-gradient(ellipse at center, rgba(40, 20, 5, 0.85) 0%, rgba(0, 0, 0, 0.94) 70%);
  display: flex; align-items: center; justify-content: center;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
/* Same fix as StopConfirmModal: don't catch clicks while fading out. */
.rm-fade-leave-active .rm-backdrop,
.rm-fade-leave-to .rm-backdrop { pointer-events: none; }
.rm-scanlines {
  position: absolute; inset: 0; pointer-events: none;
  background: repeating-linear-gradient(
    0deg,
    rgba(255, 176, 32, 0.03) 0px,
    rgba(255, 176, 32, 0.03) 1px,
    transparent 1px, transparent 3px
  );
  opacity: 0.6;
}

.rm-card {
  position: relative;
  width: min(720px, 92vw);
  background: linear-gradient(180deg, #1a1106, #06080b);
  border: 2px solid #ffb020;
  border-radius: 8px;
  box-shadow:
    0 0 64px rgba(255, 176, 32, 0.45),
    0 0 120px rgba(255, 140, 32, 0.18),
    0 1px 0 rgba(255, 255, 255, 0.04) inset;
  color: #ffb020;
  overflow: hidden;
  animation: rm-pulse 2.4s ease-in-out infinite;
}
/* phase-specific accent */
.rm-phase-starting    { border-color: #ffd060; }
.rm-phase-active      { border-color: #ffb020; }
.rm-phase-finishing   { border-color: #ff8c20; }

/* ── header ── */
.rm-head {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 22px 16px;
  background: linear-gradient(90deg, #3a2810, #1a1106);
  border-bottom: 1px solid rgba(255, 176, 32, 0.4);
}
.rm-led {
  width: 18px; height: 18px; border-radius: 50%;
  background: #ffb020;
  box-shadow: 0 0 18px #ffb020, 0 0 3px #fff inset;
  flex-shrink: 0;
  animation: rm-blink 0.9s steps(2, end) infinite;
}
.rm-led-starting  { background: #ffd060; box-shadow: 0 0 18px #ffd060, 0 0 3px #fff inset; }
.rm-led-active    { background: #ffb020; }
.rm-led-finishing { background: #ff8c20; box-shadow: 0 0 18px #ff8c20, 0 0 3px #fff inset; }
.rm-title {
  font-weight: 900; font-size: 18px; letter-spacing: 4px;
  text-shadow: 0 0 8px rgba(255, 176, 32, 0.6);
}
.rm-subtitle {
  margin-left: auto; font-size: 11px; letter-spacing: 2px; color: #c69a4a;
}

/* ── body shared ── */
.rm-body { padding: 22px; }

/* ── boot log (STARTING + FINISHING) ── */
.rm-bootlog {
  background: #06080b;
  border: 1px solid rgba(255, 176, 32, 0.3);
  border-radius: 4px;
  padding: 16px 20px;
  font-size: 13px;
  font-family: inherit;
  min-height: 200px;
}
.rm-log-line {
  display: grid;
  grid-template-columns: 18px 1fr auto;
  gap: 10px;
  align-items: center;
  padding: 4px 0;
  letter-spacing: 1.4px;
  transition: color 0.25s, opacity 0.25s;
}
.rm-log-prompt { color: #5a4214; font-weight: 700; }
.rm-log-text { font-weight: 700; }
.rm-log-status { color: #c69a4a; font-size: 11px; letter-spacing: 1px; }

.rm-log-pending { color: #5a4214; opacity: 0.55; }
.rm-log-pending .rm-log-prompt { color: #3a2810; }
.rm-log-active { color: #ffd060; text-shadow: 0 0 6px rgba(255, 208, 96, 0.4); }
.rm-log-active .rm-log-status { color: #ffd060; }
.rm-log-done { color: #69d180; }
.rm-log-done .rm-log-status { color: #69d180; }

.rm-check { color: #69d180; font-weight: 900; }
.rm-spin {
  color: #ffd060;
  display: inline-block;
  animation: rm-spin 0.9s linear infinite;
}

.rm-hint-text {
  margin-top: 16px;
  padding: 8px 12px;
  border-top: 1px dashed rgba(255, 176, 32, 0.2);
  font-size: 10.5px;
  letter-spacing: 2px;
  color: #c69a4a;
  text-align: center;
  animation: rm-pulse-text 1.8s ease-in-out infinite;
}

/* ── instructions (ACTIVE) ── */
.rm-instr {
  display: flex; align-items: flex-start; gap: 14px;
  padding: 14px 16px;
  border: 1px solid rgba(255, 176, 32, 0.25);
  border-radius: 4px;
  margin-bottom: 10px;
  background: rgba(255, 176, 32, 0.04);
}
.rm-step-num {
  font-size: 22px; font-weight: 900; letter-spacing: 2px;
  color: #ff8c20; min-width: 36px;
  text-shadow: 0 0 6px rgba(255, 140, 32, 0.5);
}
.rm-step-title {
  font-size: 13.5px; font-weight: 700; color: #ffb020;
  letter-spacing: 0.6px; margin-bottom: 4px;
}
.rm-step-title kbd {
  background: #06080b; border: 1px solid #5a4214; border-radius: 2px;
  padding: 1px 6px; margin: 0 2px; font-size: 11px;
  color: #ff8c20; letter-spacing: 1.5px;
}
.rm-step-hint { font-size: 11px; color: #c69a4a; }

.rm-meter {
  display: flex; align-items: center; gap: 10px;
  margin-top: 14px;
  padding: 10px 14px;
  background: #06080b;
  border: 1px solid rgba(255, 176, 32, 0.3);
  border-radius: 3px;
  font-size: 11px; letter-spacing: 1.5px;
}
.rm-meter-led {
  width: 8px; height: 8px; border-radius: 50%;
  background: #00ff66; box-shadow: 0 0 8px #00ff66;
  animation: rm-blink 1.2s steps(2, end) infinite;
}
.rm-meter-label { color: #c69a4a; }
.rm-meter-value { color: #ffb020; font-weight: 700; font-variant-numeric: tabular-nums; }
.rm-meter-sep { color: rgba(255, 176, 32, 0.3); padding: 0 4px; }

/* ── error ── */
.rm-error {
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(255, 64, 32, 0.1);
  border: 1px solid rgba(255, 64, 32, 0.5);
  border-radius: 3px;
  color: #ff8c20; font-size: 11.5px;
}

/* ── footer ── */
.rm-foot {
  display: flex; gap: 12px;
  padding: 16px 22px;
  background: rgba(0, 0, 0, 0.4);
  border-top: 1px solid rgba(255, 176, 32, 0.25);
}
.rm-btn {
  flex: 1;
  padding: 14px 16px;
  border: 1px solid #5a4214;
  background: #06080b;
  color: #ffb020;
  font-family: inherit;
  font-weight: 800; letter-spacing: 2px; font-size: 12.5px;
  cursor: pointer; border-radius: 3px;
  transition: all 0.15s;
  text-transform: uppercase;
}
.rm-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.rm-btn:not(:disabled):hover { background: #1a1106; box-shadow: 0 0 14px rgba(255, 176, 32, 0.4); }
.rm-cancel { flex: 0 0 30%; color: #c69a4a; font-size: 11px; }
.rm-confirm {
  border-color: #ff8c20;
  color: #ff8c20;
  box-shadow: 0 0 12px rgba(255, 140, 32, 0.25) inset;
}
.rm-confirm:not(:disabled):hover {
  box-shadow: 0 0 24px rgba(255, 140, 32, 0.6), 0 0 12px rgba(255, 140, 32, 0.25) inset;
  background: #2a1c08;
}

/* ── keyframes ── */
@keyframes rm-blink { 50% { opacity: 0.35; } }
@keyframes rm-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
@keyframes rm-pulse {
  0%, 100% { box-shadow: 0 0 48px rgba(255, 176, 32, 0.35), 0 0 96px rgba(255, 140, 32, 0.14); }
  50%      { box-shadow: 0 0 80px rgba(255, 176, 32, 0.55), 0 0 160px rgba(255, 140, 32, 0.24); }
}
@keyframes rm-pulse-text { 50% { opacity: 0.5; } }

.rm-fade-enter-active, .rm-fade-leave-active { transition: opacity 0.25s ease; }
.rm-fade-enter-from, .rm-fade-leave-to { opacity: 0; }
.rm-fade-enter-active .rm-card,
.rm-fade-leave-active .rm-card {
  transition: transform 0.32s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.rm-fade-enter-from .rm-card,
.rm-fade-leave-to .rm-card { transform: scale(0.94); }
</style>
