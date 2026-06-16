<template>
  <Transition name="cal-fade">
    <div v-if="conn.calibrationOpen && !conn.calibrationDismissed" class="cal-backdrop" @click.self="onDismiss">
      <div class="cal-modal phosphor">
        <!-- Header -->
        <header class="cal-head">
          <span class="cal-led" :class="{ live: boardDetected }" />
          <span class="cal-title">CAMERA CALIBRATION</span>
          <span class="cal-phase" :class="phaseClass">{{ phaseLabel }}</span>
          <span v-if="stageBadge" class="cal-stage-badge">{{ stageBadge }}</span>
          <button class="cal-dismiss" @click="onDismiss"
                  title="Hide this panel — calibration keeps running, re-open from the banner">
            DISMISS
          </button>
          <button class="cal-x" @click="onClose" title="Close (cancels a running session)">✕</button>
        </header>

        <!-- Target selector -->
        <div class="cal-targets">
          <button v-for="t in targets" :key="t"
                  class="cal-target-btn" :class="{ sel: target === t }"
                  :disabled="busy"
                  @click="selectTarget(t)">
            {{ t.toUpperCase() }}
          </button>
        </div>

        <!-- SIDE dependency notice -->
        <div v-if="target === 'side'" class="cal-note">
          ⚠ SIDE uses the wrist cameras as reference — calibrate LEFT (and RIGHT, for the
          two-arm solve) first. You'll pose the LEFT arm and confirm, then the RIGHT arm
          and confirm; the side extrinsic + inter-arm transform are then solved jointly.
        </div>

        <!-- Live annotated stream -->
        <div class="cal-stage">
          <img v-if="streamSrc" :src="streamSrc" class="cal-feed" alt="calibration feed" />
          <div v-else class="cal-feed cal-feed-empty">no feed</div>

          <!-- Board lock badge -->
          <div class="cal-badge" :class="{ on: boardDetected }">
            <span class="cal-badge-dot" />
            {{ boardDetected ? 'BOARD LOCKED' : 'SEARCHING…' }}
          </div>

          <!-- Collecting progress overlay -->
          <div v-if="phase === 'collecting'" class="cal-progress">
            <div class="cal-progress-bar">
              <div class="cal-progress-fill" :style="{ width: pct + '%' }" />
            </div>
            <span class="cal-progress-txt">
              <template v-if="isSide && stage">{{ stage.toUpperCase() }} arm — </template>samples
              {{ samples }}/{{ samplesTarget || '?' }}
            </span>
          </div>

          <!-- Solving spinner -->
          <div v-if="phase === 'solving'" class="cal-solving">
            <span class="cal-spinner" /> SOLVING…
          </div>
        </div>

        <!-- Message / error -->
        <div v-if="message" class="cal-msg" :class="{ err: phase === 'failed' }">{{ message }}</div>

        <!-- Result readout -->
        <div v-if="phase === 'done' && metrics" class="cal-result">
          <div class="cal-grade" :class="gradeClass">{{ grade }}</div>
          <ul class="cal-metrics">
            <li v-for="[k, v] in flatMetricEntries" :key="k">
              <span class="mk">{{ prettyKey(k) }}</span>
              <span class="mv">{{ fmt(v) }}</span>
            </li>
          </ul>
          <!-- Per-arm breakdown (two-arm side solve) -->
          <div v-for="[arm, am] in armMetrics" :key="arm" class="cal-arm">
            <div class="cal-arm-title">{{ arm }} ARM</div>
            <ul class="cal-metrics">
              <li v-for="(v, k) in am" :key="k">
                <span class="mk">{{ prettyKey(k) }}</span>
                <span class="mv">{{ fmt(v) }}</span>
              </li>
            </ul>
          </div>
          <div v-if="outputPath" class="cal-out">→ {{ outputPath }}</div>
        </div>

        <!-- Footer controls -->
        <footer class="cal-foot">
          <button v-if="canStart" class="cal-btn primary" @click="onStart">START</button>
          <button v-if="phase === 'positioning'" class="cal-btn primary"
                  :disabled="!boardDetected" @click="onConfirm"
                  :title="boardDetected ? 'Lock pose and run trajectory' : 'Position the board in view first'">
            {{ isSide && stage ? `CONFIRM ${stage.toUpperCase()}` : 'CONFIRM POSITION' }}
          </button>
          <button v-if="busy" class="cal-btn danger" @click="onCancel">CANCEL</button>
          <button v-if="phase === 'done' || phase === 'failed' || phase === 'cancelled'"
                  class="cal-btn" @click="onReset">NEW</button>
          <button class="cal-btn ghost" @click="onClose">CLOSE</button>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, computed, watch } from 'vue';
import { useConnectionStore } from '@/stores/connection';

const conn = useConnectionStore();
const targets = ['left', 'right', 'side'];

// Local target mirrors the store (so the stream can switch even before START).
const target = ref(conn.calibTarget || 'left');
const streamNonce = ref(0);

const status = computed(() => conn.calibStatus || { phase: 'idle' });
const phase = computed(() => status.value.phase || 'idle');
const boardDetected = computed(() => !!status.value.board_detected);
const samples = computed(() => status.value.samples_collected || 0);
const samplesTarget = computed(() => status.value.samples_target || 0);
const metrics = computed(() => status.value.metrics || null);
const outputPath = computed(() => status.value.output_path || '');
const message = computed(() => status.value.error || status.value.message || '');

// Two-arm side flow: which arm is being posed/collected ("left" | "right").
const isSide = computed(() => target.value === 'side');
const stage = computed(() => status.value.stage || '');
const stageBadge = computed(() =>
  isSide.value && stage.value && ['positioning', 'collecting'].includes(phase.value)
    ? `${stage.value.toUpperCase()} ARM` : '');

const busy = computed(() => ['positioning', 'collecting', 'solving'].includes(phase.value));
const canStart = computed(() => ['idle', 'done', 'failed', 'cancelled'].includes(phase.value));
const pct = computed(() =>
  samplesTarget.value ? Math.min(100, Math.round((samples.value / samplesTarget.value) * 100)) : 0);

const phaseLabel = computed(() => ({
  idle: 'READY', positioning: 'POSITION', collecting: 'COLLECTING',
  solving: 'SOLVING', done: 'DONE', failed: 'FAILED', cancelled: 'CANCELLED',
}[phase.value] || phase.value.toUpperCase()));
const phaseClass = computed(() => `ph-${phase.value}`);

// Show the annotated stream whenever the modal is open and backend is up.
const streamSrc = computed(() =>
  conn.backend === 'up'
    ? `${conn.backendUrl}/calibration/stream?target=${target.value}&n=${streamNonce.value}`
    : null);

// ── quality grade (wrist: board_consistency_error_mm; side: alignment mm) ──
const gradeBasisMm = computed(() => {
  const m = metrics.value || {};
  return m.board_consistency_error_mm ?? m.cross_camera_alignment_error_mm ?? null;
});
const grade = computed(() => {
  const e = gradeBasisMm.value;
  if (e == null) return 'DONE';
  if (e < 1) return 'EXCELLENT';
  if (e < 5) return 'GOOD';
  if (e < 10) return 'ACCEPTABLE';
  return 'POOR';
});
const gradeClass = computed(() => `g-${grade.value.toLowerCase()}`);

// Flat (scalar) metrics for the top list; nested per-arm objects are shown
// separately via armMetrics so we never render "[object Object]".
const flatMetricEntries = computed(() =>
  Object.entries(metrics.value || {}).filter(([, v]) => v == null || typeof v !== 'object'));
const armMetrics = computed(() => {
  const m = metrics.value || {};
  const out = [];
  if (m.left && typeof m.left === 'object') out.push(['LEFT', m.left]);
  if (m.right && typeof m.right === 'object') out.push(['RIGHT', m.right]);
  return out;
});

function prettyKey(k) {
  return String(k).replace(/_/g, ' ').replace(/\berror\b/i, '').replace(/\s+/g, ' ').trim();
}
function fmt(v) {
  if (typeof v === 'number') return Number.isInteger(v) ? v : v.toFixed(2);
  return v;
}

function selectTarget(t) {
  if (busy.value) return;
  target.value = t;
  conn.calibTarget = t;
  streamNonce.value++;          // force the MJPEG <img> to reconnect
  void conn.pollCalibrationOnce();
}

async function onStart() {
  const r = await conn.startCalibration(target.value);
  if (!r.ok) conn.lastError = `Calibration start failed: ${r.error}`;
}
async function onConfirm() {
  const r = await conn.confirmCalibPosition();
  if (!r.ok) conn.lastError = `Confirm failed: ${r.error}`;
}
async function onCancel() {
  await conn.cancelCalibration();
}
function onReset() {
  // Clear the local view back to idle for a fresh run (status refreshes on poll).
  conn.calibStatus = { phase: 'idle' };
}
function onDismiss() {
  // Hide the panel but keep the session + polling alive (banner re-opens it).
  conn.dismissCalibration();
}
async function onClose() {
  // A floating/collecting arm must not be left unattended — abort on close.
  if (busy.value) await conn.cancelCalibration();
  conn.closeCalibration();
}

// Poll only while the modal is open; keep local target in sync on open.
watch(() => conn.calibrationOpen, (open) => {
  if (open) {
    target.value = conn.calibTarget || 'left';
    streamNonce.value++;
    conn.startCalibPolling();
  } else {
    conn.stopCalibPolling();
  }
});

// Re-opening from the banner remounts the <img>; bump the nonce so the MJPEG
// stream reconnects cleanly instead of resuming a half-dead connection.
watch(() => conn.calibrationDismissed, (dismissed) => {
  if (!dismissed && conn.calibrationOpen) streamNonce.value++;
});

// Esc dismisses (keeps the session running); use ✕ / CLOSE to actually cancel.
function onKey(e) { if (e.key === 'Escape') onDismiss(); }
watch(() => conn.calibrationOpen, (o) => {
  if (o) window.addEventListener('keydown', onKey);
  else window.removeEventListener('keydown', onKey);
});
</script>

<style scoped>
.cal-backdrop {
  position: fixed; inset: 0; z-index: 10200;
  background: rgba(0, 0, 0, 0.7); backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.cal-modal {
  width: min(1240px, 97vw); max-height: 96vh; overflow-y: auto;
  background: linear-gradient(180deg, #160d28, #06080b);
  border: 1px solid #b082ff; border-radius: 8px;
  box-shadow: 0 0 36px rgba(176, 130, 255, 0.35), 0 1px 0 rgba(255,255,255,0.03) inset;
  color: #d7d0e8; padding: 0 0 14px;
}

/* header */
.cal-head {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px; border-bottom: 1px solid #2a2040;
}
.cal-led {
  width: 10px; height: 10px; border-radius: 50%;
  background: #5a4a7a; box-shadow: 0 0 6px #5a4a7a;
}
.cal-led.live { background: #69d180; box-shadow: 0 0 10px #69d180; animation: blink 1.2s infinite; }
.cal-title { font-weight: 800; letter-spacing: 1.5px; color: #c2a3ff; text-shadow: 0 0 8px rgba(176,130,255,.6); }
.cal-phase { margin-left: 8px; font-size: 11px; padding: 2px 8px; border-radius: 4px;
  border: 1px solid #2a2040; color: #9a8cc0; letter-spacing: 1px; }
.cal-phase.ph-done { color: #88e8a0; border-color: #2e5a38; }
.cal-phase.ph-failed { color: #ff6a5a; border-color: #5a2420; }
.cal-phase.ph-collecting, .cal-phase.ph-positioning, .cal-phase.ph-solving { color: #ffd27a; border-color: #5a4720; }
.cal-stage-badge { font-size: 10.5px; font-weight: 800; letter-spacing: 1.5px; padding: 2px 8px;
  border-radius: 4px; color: #e3d6ff; background: linear-gradient(180deg,#2c1850,#150a28);
  border: 1px solid #b082ff; box-shadow: 0 0 10px rgba(176,130,255,.35); }
.cal-dismiss { margin-left: auto; padding: 4px 10px; font: inherit; font-size: 10.5px;
  font-weight: 800; letter-spacing: 1.5px; color: #9a8cc0; background: #160d28;
  border: 1px solid #3a2c54; border-radius: 3px; cursor: pointer; transition: all .15s; }
.cal-dismiss:hover { color: #c2a3ff; border-color: #b082ff; box-shadow: 0 0 10px rgba(176,130,255,.3); }
.cal-x { background: none; border: none; color: #8a7fb0; cursor: pointer; font-size: 15px; }
.cal-x:hover { color: #ff6a5a; }

/* targets */
.cal-targets { display: flex; gap: 8px; padding: 12px 14px 4px; }
.cal-target-btn {
  flex: 1; padding: 9px 0; background: rgba(26,14,40,.5);
  border: 1px solid rgba(176,130,255,.4); border-radius: 6px;
  color: #b9a8e0; font: inherit; font-weight: 800; letter-spacing: 1.5px; cursor: pointer;
  transition: all .15s;
}
.cal-target-btn:hover:not(:disabled) { border-color: #b082ff; background: rgba(36,20,56,.85); }
.cal-target-btn.sel { background: linear-gradient(180deg,#2c1850,#150a28); border-color:#b082ff;
  color:#e3d6ff; box-shadow: 0 0 12px rgba(176,130,255,.4) inset; }
.cal-target-btn:disabled { opacity: .4; cursor: not-allowed; }

/* side notice */
.cal-note {
  margin: 8px 14px; padding: 8px 10px; font-size: 12px; line-height: 1.4;
  color: #ffd27a; background: rgba(60,44,12,.4); border: 1px solid #5a4720; border-radius: 5px;
}

/* stage */
.cal-stage { position: relative; margin: 8px 14px; border: 1px solid #2a2040; border-radius: 6px;
  overflow: hidden; background: #000; min-height: 220px; display: flex; }
.cal-feed { width: 100%; display: block; object-fit: contain; max-height: 74vh; }
.cal-feed-empty { align-items: center; justify-content: center; color: #5a4a7a; min-height: 220px; }
.cal-badge {
  position: absolute; top: 10px; right: 10px; display: flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 800; letter-spacing: 1px;
  background: rgba(10,10,14,.7); border: 1px solid #4a3a5a; color: #9a8cc0;
}
.cal-badge.on { color: #88e8a0; border-color: #2e5a38; box-shadow: 0 0 12px rgba(105,209,128,.4); }
.cal-badge-dot { width: 8px; height: 8px; border-radius: 50%; background: #5a4a7a; }
.cal-badge.on .cal-badge-dot { background: #69d180; box-shadow: 0 0 8px #69d180; animation: blink 1s infinite; }

.cal-progress { position: absolute; left: 10px; right: 10px; bottom: 10px;
  display: flex; align-items: center; gap: 10px; }
.cal-progress-bar { flex: 1; height: 10px; background: rgba(10,10,14,.8); border: 1px solid #2a2040;
  border-radius: 5px; overflow: hidden; }
.cal-progress-fill { height: 100%; background: linear-gradient(90deg,#7a52d0,#b082ff);
  box-shadow: 0 0 10px rgba(176,130,255,.6); transition: width .3s; }
.cal-progress-txt { font-size: 12px; color: #c2a3ff; white-space: nowrap; }

.cal-solving { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  gap: 10px; font-weight: 800; letter-spacing: 2px; color: #ffd27a; background: rgba(6,8,11,.45); }
.cal-spinner { width: 16px; height: 16px; border: 2px solid #5a4720; border-top-color: #ffd27a;
  border-radius: 50%; animation: spin .8s linear infinite; }

/* message + result */
.cal-msg { margin: 8px 14px; font-size: 12px; line-height: 1.4; color: #b9a8e0; }
.cal-msg.err { color: #ff8a7a; }
.cal-result { margin: 8px 14px; padding: 10px; border: 1px solid #2a2040; border-radius: 6px;
  background: rgba(20,14,32,.5); }
.cal-grade { font-weight: 800; letter-spacing: 2px; font-size: 15px; margin-bottom: 8px; }
.g-excellent { color: #69d180; } .g-good { color: #9ad36a; }
.g-acceptable { color: #ffd27a; } .g-poor { color: #ff6a5a; }
.cal-metrics { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 4px 18px; }
.cal-metrics li { display: flex; justify-content: space-between; font-size: 12px; }
.mk { color: #9a8cc0; } .mv { color: #e3d6ff; font-weight: 700; }
.cal-arm { margin-top: 10px; padding-top: 8px; border-top: 1px dashed #2a2040; }
.cal-arm-title { font-size: 11px; font-weight: 800; letter-spacing: 1.5px; color: #c2a3ff; margin-bottom: 4px; }
.cal-out { margin-top: 8px; font-size: 11px; color: #7a6ca0; word-break: break-all; }

/* footer */
.cal-foot { display: flex; gap: 8px; justify-content: flex-end; padding: 12px 14px 0; }
.cal-btn { padding: 8px 16px; border-radius: 5px; font: inherit; font-weight: 800; letter-spacing: 1px;
  cursor: pointer; background: #1a1228; border: 1px solid #3a2c54; color: #c2a3ff; transition: all .15s; }
.cal-btn:hover:not(:disabled) { border-color: #b082ff; box-shadow: 0 0 10px rgba(176,130,255,.4); }
.cal-btn:disabled { opacity: .4; cursor: not-allowed; }
.cal-btn.primary { background: linear-gradient(180deg,#2c1850,#150a28); border-color:#b082ff; color:#e3d6ff; }
.cal-btn.danger { border-color: rgba(255,68,56,.5); color: #ff6a5a; }
.cal-btn.danger:hover { box-shadow: 0 0 10px rgba(255,68,56,.4); border-color:#ff4438; }
.cal-btn.ghost { background: transparent; color: #8a7fb0; }

.cal-fade-enter-active, .cal-fade-leave-active { transition: opacity .18s; }
.cal-fade-enter-from, .cal-fade-leave-to { opacity: 0; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.4} }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
