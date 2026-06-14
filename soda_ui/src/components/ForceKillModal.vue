<template>
  <Transition name="fk-fade">
    <div v-if="open" class="fk-backdrop" @click.self="onCancel">
      <!-- danger scanlines on top -->
      <div class="fk-scanlines" />

      <div class="fk-card" :class="phaseClass">
        <!-- hazard-stripe border that wraps everything -->
        <div class="fk-stripe-border">
          <div class="fk-stripe fk-stripe-top" />
          <div class="fk-stripe fk-stripe-bot" />
        </div>

        <header class="fk-head">
          <span class="fk-led" />
          <span class="fk-title">{{ headerTitle }}</span>
          <span class="fk-subtitle">{{ headerSubtitle }}</span>
        </header>

        <div class="fk-body">
          <!-- ░ Idle/arming: hold-to-confirm ring ░ -->
          <div v-if="phase !== 'fired'" class="fk-warn">
            This will <b>SIGKILL</b> every known stack process:
          </div>
          <ul v-if="phase !== 'fired'" class="fk-targets">
            <li>scripts/teleop_quest.py · teleop_viewer.py</li>
            <li>soda_os.main (backend)</li>
            <li>launchers/launch_servers.py</li>
            <li>launchers/launch_with_zerog.py (zero-gravity)</li>
            <li class="fk-targets-end">+ kill_servers.sh sweep for anything missed</li>
          </ul>
          <p v-if="phase !== 'fired'" class="fk-note">
            The launcher (this UI) stays alive. Backend and HW go down — you'll
            return to the LauncherCard to re-launch.
          </p>

          <!-- Hold-to-confirm button: circular progress ring around skull -->
          <div class="fk-ring-wrap">
            <button
              class="fk-ring-btn"
              :class="phaseClass"
              :disabled="phase === 'firing' || phase === 'fired'"
              @pointerdown="startHold"
              @pointerup="cancelHold"
              @pointercancel="cancelHold"
              @pointerleave="cancelHold"
              :aria-label="phase === 'fired' ? 'Force kill complete' : 'Hold to force kill'"
            >
              <!-- circular progress (SVG ring) -->
              <svg class="fk-ring-svg" viewBox="0 0 120 120" aria-hidden="true">
                <circle class="fk-ring-track"
                        cx="60" cy="60" r="54" fill="none" stroke-width="6" />
                <circle class="fk-ring-fill"
                        cx="60" cy="60" r="54" fill="none" stroke-width="6"
                        :stroke-dasharray="circumference"
                        :stroke-dashoffset="dashOffset"
                        transform="rotate(-90 60 60)" />
              </svg>
              <div class="fk-ring-core">
                <div class="fk-glyph">
                  <span v-if="phase === 'fired'">✓</span>
                  <span v-else>⚠</span>
                </div>
                <div class="fk-ring-label">
                  <span v-if="phase === 'idle'">HOLD</span>
                  <span v-else-if="phase === 'arming'">{{ progressPct }}%</span>
                  <span v-else-if="phase === 'firing'">FIRING…</span>
                  <span v-else-if="phase === 'fired'">DONE</span>
                </div>
              </div>
            </button>
            <div class="fk-ring-hint">
              <span v-if="phase === 'idle'">PRESS AND HOLD 2 s TO ARM SIGKILL</span>
              <span v-else-if="phase === 'arming'">KEEP HOLDING — RELEASE TO ABORT</span>
              <span v-else-if="phase === 'firing'">SENDING SIGKILL TO ALL PROCESSES</span>
              <span v-else-if="phase === 'fired'">{{ firedSummary }}</span>
            </div>
          </div>

          <div v-if="errorText" class="fk-error">! {{ errorText }}</div>
        </div>

        <footer class="fk-foot">
          <button class="fk-btn fk-cancel"
                  :disabled="phase === 'firing'"
                  @click="onCancel">
            {{ phase === 'fired' ? 'CLOSE' : 'CANCEL' }}
          </button>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue';
import { useConnectionStore } from '@/stores/connection';

const props = defineProps({
  open: { type: Boolean, default: false },
});
const emit = defineEmits(['close']);
const conn = useConnectionStore();

// Phase machine: idle → arming (holding) → firing (request in flight) → fired
const phase = ref('idle');        // 'idle' | 'arming' | 'firing' | 'fired'
const progress = ref(0);          // 0..1
const errorText = ref(null);
const firedSummary = ref('STACK TERMINATED');

const HOLD_MS = 2000;
const circumference = 2 * Math.PI * 54;   // matches SVG r=54

const dashOffset = computed(() => circumference * (1 - progress.value));
const progressPct = computed(() => Math.round(progress.value * 100));

const phaseClass = computed(() => `fk-phase-${phase.value}`);

const headerTitle = computed(() => ({
  idle: 'EMERGENCY · FORCE KILL',
  arming: 'ARMING SIGKILL',
  firing: 'FORCE KILL ACTIVE',
  fired: 'FORCE KILL COMPLETE',
}[phase.value]));
const headerSubtitle = computed(() => ({
  idle: 'HOLD-TO-CONFIRM',
  arming: `${progressPct.value}% ARMED`,
  firing: 'SENDING SIGNALS',
  fired: 'STACK DOWN',
}[phase.value]));

// ── hold loop ─────────────────────────────────────────────────────
let rafId = null;
let holdStart = 0;

function startHold() {
  if (phase.value !== 'idle' && phase.value !== 'arming') return;
  phase.value = 'arming';
  errorText.value = null;
  holdStart = performance.now();
  loop();
}
function loop() {
  if (phase.value !== 'arming') return;
  const elapsed = performance.now() - holdStart;
  progress.value = Math.min(1, elapsed / HOLD_MS);
  if (progress.value >= 1) {
    fire();
    return;
  }
  rafId = requestAnimationFrame(loop);
}
function cancelHold() {
  if (phase.value === 'arming') {
    phase.value = 'idle';
    progress.value = 0;
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
  }
}

async function fire() {
  phase.value = 'firing';
  progress.value = 1;
  if (rafId) cancelAnimationFrame(rafId);
  const r = await conn.forceKill();
  if (!r.ok) {
    errorText.value = `Force kill failed: ${r.error}`;
    phase.value = 'idle';
    progress.value = 0;
    return;
  }
  firedSummary.value = r.killed ? `${r.killed} PROCESS(ES) TERMINATED` : 'STACK TERMINATED';
  phase.value = 'fired';
}

function onCancel() {
  cancelHold();
  emit('close');
}

// Reset state every time we re-open
watch(() => props.open, (open) => {
  if (open) {
    phase.value = 'idle';
    progress.value = 0;
    errorText.value = null;
  } else {
    cancelHold();
  }
});

// Escape always closes (allowed even mid-fire)
function onKey(e) { if (e.key === 'Escape' && phase.value !== 'firing') onCancel(); }
watch(() => props.open, (o) => {
  if (o) window.addEventListener('keydown', onKey);
  else window.removeEventListener('keydown', onKey);
});
onUnmounted(() => {
  window.removeEventListener('keydown', onKey);
  if (rafId) cancelAnimationFrame(rafId);
});
</script>

<style scoped>
.fk-backdrop {
  position: fixed; inset: 0; z-index: 10000;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(ellipse at center, rgba(60, 0, 0, 0.7) 0%, rgba(0, 0, 0, 0.92) 75%);
  backdrop-filter: blur(3px);
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.fk-scanlines {
  position: absolute; inset: 0; pointer-events: none;
  background: repeating-linear-gradient(
    0deg,
    rgba(255, 48, 48, 0.04) 0px,
    rgba(255, 48, 48, 0.04) 1px,
    transparent 1px, transparent 3px
  );
}

.fk-card {
  position: relative;
  width: min(620px, 94vw);
  background: linear-gradient(180deg, #160606, #06080b);
  border: 2px solid #ff3030;
  border-radius: 8px;
  box-shadow:
    0 0 64px rgba(255, 48, 48, 0.55),
    0 0 140px rgba(255, 48, 48, 0.22),
    0 1px 0 rgba(255, 255, 255, 0.04) inset;
  color: #ffaaaa;
  overflow: hidden;
  animation: fk-pulse 2.0s ease-in-out infinite;
}
.fk-phase-arming { border-color: #ff6060; }
.fk-phase-firing { border-color: #ff8030; animation: fk-shake 0.18s ease-in-out infinite; }
.fk-phase-fired  { border-color: #ffb060; animation: none; }

/* ── hazard stripes top + bottom ── */
.fk-stripe-border {
  position: absolute; inset: 0; pointer-events: none;
}
.fk-stripe {
  position: absolute; left: 0; right: 0; height: 6px;
  background: repeating-linear-gradient(
    -45deg,
    #ff3030 0 12px,
    #1a0606 12px 22px
  );
  opacity: 0.85;
}
.fk-stripe-top { top: 0; }
.fk-stripe-bot { bottom: 0; }

/* ── header ── */
.fk-head {
  position: relative;
  display: flex; align-items: center; gap: 14px;
  padding: 22px 22px 16px;
  background: linear-gradient(90deg, #3a0a0a, #160606);
  border-bottom: 1px solid rgba(255, 48, 48, 0.45);
}
.fk-led {
  width: 18px; height: 18px; border-radius: 50%;
  background: #ff3030; box-shadow: 0 0 18px #ff3030, 0 0 3px #fff inset;
  flex-shrink: 0; animation: fk-blink 0.45s steps(2, end) infinite;
}
.fk-title {
  font-weight: 900; font-size: 16px; letter-spacing: 3px; color: #ff6060;
  text-shadow: 0 0 10px rgba(255, 96, 96, 0.6);
}
.fk-subtitle {
  margin-left: auto; font-size: 11px; letter-spacing: 1.6px; color: #ff9090;
}

/* ── body ── */
.fk-body { padding: 22px; position: relative; }
.fk-warn { font-size: 13px; color: #ffaaaa; margin: 0 0 10px; letter-spacing: 0.6px; }
.fk-warn b { color: #ff5050; letter-spacing: 1px; }
.fk-targets {
  margin: 0 0 14px; padding: 10px 14px 10px 28px;
  font-size: 11.5px; color: #c69090; letter-spacing: 0.6px;
  background: rgba(255, 48, 48, 0.05);
  border: 1px solid rgba(255, 48, 48, 0.22);
  border-radius: 3px;
}
.fk-targets li { padding: 1px 0; }
.fk-targets-end { color: #997070; margin-top: 4px; font-style: italic; }
.fk-note { font-size: 11px; color: #c69090; margin: 0 0 16px; }

/* ── hold-to-confirm ring ── */
.fk-ring-wrap {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  padding: 8px 0 6px;
}
.fk-ring-btn {
  position: relative;
  width: 150px; height: 150px;
  border: none; background: transparent;
  cursor: pointer; outline: none;
  padding: 0;
  user-select: none;
  -webkit-touch-callout: none;
}
.fk-ring-btn:disabled { cursor: default; }

.fk-ring-svg {
  position: absolute; inset: 0;
  width: 100%; height: 100%;
}
.fk-ring-track {
  stroke: rgba(255, 48, 48, 0.18);
}
.fk-ring-fill {
  stroke: #ff3030;
  stroke-linecap: round;
  filter: drop-shadow(0 0 4px rgba(255, 48, 48, 0.7));
  transition: stroke 0.18s ease;
}
.fk-phase-arming .fk-ring-fill { stroke: #ff6060; }
.fk-phase-firing .fk-ring-fill { stroke: #ff8030; }
.fk-phase-fired  .fk-ring-fill { stroke: #69d180; filter: drop-shadow(0 0 6px rgba(105, 209, 128, 0.8)); }

.fk-ring-core {
  position: absolute; inset: 18px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #2a0a0a, #06080b 80%);
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  border: 1px solid rgba(255, 48, 48, 0.45);
  transition: border-color 0.18s, background 0.22s;
}
.fk-phase-arming .fk-ring-core { border-color: #ff6060; }
.fk-phase-firing .fk-ring-core { border-color: #ff8030; }
.fk-phase-fired  .fk-ring-core {
  border-color: #69d180;
  background: radial-gradient(circle at 35% 30%, #0a2a0a, #06080b 80%);
}

.fk-glyph {
  font-size: 38px;
  font-weight: 900;
  line-height: 1;
  color: #ff3030;
  text-shadow: 0 0 14px rgba(255, 48, 48, 0.8);
  margin-bottom: 2px;
}
.fk-phase-arming .fk-glyph { color: #ff6060; animation: fk-blink 0.32s steps(2, end) infinite; }
.fk-phase-firing .fk-glyph { color: #ff8030; }
.fk-phase-fired .fk-glyph {
  color: #69d180; text-shadow: 0 0 14px rgba(105, 209, 128, 0.7); animation: none;
}
.fk-ring-label {
  font-size: 11px; letter-spacing: 2px; font-weight: 800; color: #ff9090;
}
.fk-phase-firing .fk-ring-label { color: #ffb070; }
.fk-phase-fired .fk-ring-label { color: #69d180; }

.fk-ring-hint {
  margin-top: 8px;
  font-size: 10.5px;
  letter-spacing: 2px;
  color: #c69090;
  text-align: center;
}

/* ── error ── */
.fk-error {
  margin-top: 14px;
  padding: 8px 12px;
  background: rgba(255, 64, 32, 0.14);
  border: 1px solid #ff6030;
  border-radius: 3px;
  color: #ffaa70; font-size: 11.5px;
}

/* ── footer ── */
.fk-foot {
  position: relative;
  display: flex; gap: 12px;
  padding: 14px 22px;
  background: rgba(0, 0, 0, 0.4);
  border-top: 1px solid rgba(255, 48, 48, 0.3);
}
.fk-btn {
  flex: 1;
  padding: 12px 14px;
  border: 1px solid #5a1414;
  background: #06080b;
  color: #c69090;
  font-family: inherit;
  font-weight: 800; letter-spacing: 2px; font-size: 11.5px;
  cursor: pointer; border-radius: 3px;
  transition: all 0.15s;
}
.fk-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.fk-btn:not(:disabled):hover {
  background: #160606;
  box-shadow: 0 0 12px rgba(255, 48, 48, 0.3);
}

/* ── animations ── */
@keyframes fk-blink { 50% { opacity: 0.32; } }
@keyframes fk-pulse {
  0%, 100% { box-shadow: 0 0 48px rgba(255, 48, 48, 0.4), 0 0 96px rgba(255, 48, 48, 0.15); }
  50%      { box-shadow: 0 0 80px rgba(255, 48, 48, 0.65), 0 0 160px rgba(255, 48, 48, 0.28); }
}
@keyframes fk-shake {
  0%, 100% { transform: translateX(0); }
  25%      { transform: translateX(-2px); }
  75%      { transform: translateX(2px); }
}

.fk-fade-enter-active, .fk-fade-leave-active { transition: opacity 0.18s ease; }
.fk-fade-enter-from, .fk-fade-leave-to { opacity: 0; }
.fk-fade-enter-active .fk-card,
.fk-fade-leave-active .fk-card {
  transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.fk-fade-enter-from .fk-card,
.fk-fade-leave-to .fk-card {
  transform: scale(0.92) rotate(-0.4deg);
}
.fk-fade-leave-active .fk-backdrop,
.fk-fade-leave-to .fk-backdrop { pointer-events: none; }
</style>
