<template>
  <Transition name="to-fade">
    <div v-if="visible" class="to-backdrop" :class="phaseClass">
      <div class="to-scanlines" />

      <div class="to-card phosphor">
        <!-- ── header ── -->
        <header class="to-head">
          <span class="to-led" :class="{ 'to-led-rec': recording }" />
          <span class="to-title">TELEOP ACTIVE</span>

          <!-- TASK pill — sticky per-session instruction. Clicking opens the
               modal. Empty state blinks amber so it's noticed before the first
               save. -->
          <button class="to-taskpill" :class="{ 'tp-empty': !currentInstruction }"
                  @click="openInstructionModal"
                  :title="currentInstruction
                    ? `Task: ${currentInstruction}  (click to change)`
                    : 'Click to set a task — used for every episode saved next.'">
            <span class="tp-glyph">★</span>
            <span class="tp-key">TASK</span>
            <span class="tp-sep">·</span>
            <span class="tp-text">{{ currentInstruction || '(none) — click to set' }}</span>
            <span class="tp-edit">✎</span>
          </button>

          <span class="to-statpill" :class="statusClass">
            {{ statusLabel }}
          </span>
        </header>

        <!-- ── camera grid (3 tiles) ── -->
        <div class="to-cams">
          <div v-for="cam in CAMS" :key="cam.key" class="to-cam-tile">
            <div class="to-cam-label">
              <span class="to-cam-led" :class="{ on: !!camerasMap[cam.key] }" />
              <span>{{ cam.label }}</span>
            </div>
            <div class="to-cam-view">
              <img v-if="camerasMap[cam.key]" :src="camerasMap[cam.key]" class="to-cam-img" />
              <div v-else class="to-cam-empty">— no frame —</div>
            </div>
          </div>
        </div>

        <!-- ── action buttons + keyboard hints ── -->
        <div class="to-actions">
          <button class="to-btn to-btn-rec" :class="{ active: recording }"
                  @click="onKey('r')" :disabled="pending || !conn.teleopConnected">
            <span class="to-btn-key">[R]</span>
            <span class="to-btn-label">{{ recording ? 'STOP RECORDING' : 'START RECORDING' }}</span>
          </button>
          <button class="to-btn to-btn-save" @click="onKey('s')" :disabled="pending || !recording">
            <span class="to-btn-key">[S]</span>
            <span class="to-btn-label">SAVE &amp; STOP</span>
          </button>
          <button class="to-btn to-btn-discard" @click="onKey('f')" :disabled="pending || !recording">
            <span class="to-btn-key">[F]</span>
            <span class="to-btn-label">DISCARD (FAIL)</span>
          </button>
          <button class="to-btn to-btn-quit" @click="onKey('q')" :disabled="pending">
            <span class="to-btn-key">[Q]</span>
            <span class="to-btn-label">QUIT TELEOP</span>
          </button>
        </div>

        <!-- ── status footer ── -->
        <footer class="to-foot">
          <div class="to-meter">
            <span class="to-meter-led" />
            <span class="to-meter-label">UPTIME</span>
            <span class="to-meter-value">{{ uptimeText }}</span>
            <span class="to-meter-sep">·</span>
            <span class="to-meter-label">BRIDGE</span>
            <span class="to-meter-value">{{ conn.teleopConnected ? 'LIVE' : (conn.teleopClosed ? 'CLOSED' : 'CONNECTING') }}</span>
            <span class="to-meter-sep">·</span>
            <span class="to-meter-label">STATUS</span>
            <span class="to-meter-value">{{ conn.teleopStatus || '—' }}</span>
          </div>
          <button class="to-dismiss" @click="onDismiss">DISMISS OVERLAY</button>
        </footer>

        <div v-if="conn.lastError" class="to-error">! {{ conn.lastError }}</div>
      </div>

      <SaveInstructionModal
        :open="instructionModalOpen"
        :initial-text="currentInstruction"
        :recent="recentInstructions"
        @set="onInstructionSet"
        @cancel="onInstructionCancel"
      />
    </div>
  </Transition>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue';
import { useConnectionStore } from '@/stores/connection';
import SaveInstructionModal from '@/components/SaveInstructionModal.vue';

const props = defineProps({
  cameras: {
    type: Object,
    default: () => ({ left: null, side: null, right: null }),
  },
});

const conn = useConnectionStore();

// ── Per-session task instruction ─────────────────────────────────
// Persisted across launches: re-opening the UI tomorrow keeps yesterday's task.
const LS_CURRENT = 'teleop_current_task';
const LS_RECENT = 'teleop_recent_tasks';
const RECENT_MAX = 5;

function loadStr(key, dflt) {
  try { return localStorage.getItem(key) ?? dflt; } catch { return dflt; }
}
function loadArr(key) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.filter(x => typeof x === 'string' && x) : [];
  } catch { return []; }
}

const currentInstruction = ref(loadStr(LS_CURRENT, ''));
const recentInstructions = ref(loadArr(LS_RECENT));
const instructionModalOpen = ref(false);
// pendingSaveAfterSet: when S was pressed with empty task, modal opens; on
// SET we immediately continue with the save. Set false on Cancel.
let pendingSaveAfterSet = false;

function persistCurrent() {
  try { localStorage.setItem(LS_CURRENT, currentInstruction.value || ''); } catch { /* */ }
}
function pushRecent(text) {
  const t = (text || '').trim();
  if (!t) return;
  const existing = recentInstructions.value.filter(x => x !== t);
  recentInstructions.value = [t, ...existing].slice(0, RECENT_MAX);
  try { localStorage.setItem(LS_RECENT, JSON.stringify(recentInstructions.value)); } catch { /* */ }
}

function openInstructionModal() {
  pendingSaveAfterSet = false;
  instructionModalOpen.value = true;
}
async function onInstructionSet(text) {
  currentInstruction.value = text;
  persistCurrent();
  pushRecent(text);
  instructionModalOpen.value = false;
  // Tell teleop_quest right away so the next save uses it; sending eagerly
  // (rather than on every S press) means a future S keystroke gets through
  // the bridge as a single byte with no extra round-trip.
  await conn.sendTeleopInstruction(text);
  if (pendingSaveAfterSet) {
    pendingSaveAfterSet = false;
    await doSave();
  }
}
function onInstructionCancel() {
  pendingSaveAfterSet = false;
  instructionModalOpen.value = false;
}

const CAMS = [
  { key: 'left',  label: 'LEFT' },
  { key: 'side',  label: 'SIDE' },
  { key: 'right', label: 'RIGHT' },
];
const camerasMap = computed(() => props.cameras || {});

const pending = ref(false);
const startedAt = ref(null);
const tick = ref(0);
let tickTimer = null;

// ── phase / visibility ─────────────────────────────────────────────
const visible = computed(() =>
  conn.teleopRunning && !conn.teleopOverlayDismissed && !conn.teleopClosed
);

// Status semantics — teleop_quest emits "idle" | "recording" | "saving".
const statusUpper = computed(() => (conn.teleopStatus || '').toUpperCase());
const recording = computed(() => statusUpper.value.includes('REC'));

const statusLabel = computed(() => {
  if (savedFlash.value) return savedFlash.value;
  if (!conn.teleopConnected) return 'CONNECTING…';
  if (conn.teleopClosed) return 'CLOSED';
  if (recording.value) return 'RECORDING';
  return statusUpper.value || 'READY';
});
const statusClass = computed(() => {
  if (savedFlash.value) return 'sp-saved';
  if (recording.value) return 'sp-rec';
  return 'sp-ready';
});

const phaseClass = computed(() => {
  if (recording.value) return 'to-phase-rec';
  return 'to-phase-idle';
});

const uptimeText = computed(() => {
  tick.value;
  if (!startedAt.value) return '00:00';
  const s = Math.floor((Date.now() - startedAt.value) / 1000);
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${mm}:${ss}`;
});

watch(() => conn.teleopRunning, (running) => {
  if (running) {
    conn.teleopOverlayDismissed = false;
    startedAt.value = Date.now();
    if (!tickTimer) tickTimer = window.setInterval(() => { tick.value++; }, 500);
  } else {
    startedAt.value = null;
    if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
  }
}, { immediate: true });

// Push the persisted task to teleop_quest as soon as the bridge is live. Lets
// the operator just press R then S on a fresh launch without re-typing the
// task from yesterday — the pending_instruction is already there.
watch(() => conn.teleopConnected, (connected) => {
  if (connected && currentInstruction.value.trim()) {
    void conn.sendTeleopInstruction(currentInstruction.value.trim());
  }
});
onUnmounted(() => { if (tickTimer) clearInterval(tickTimer); });

// ── actions ─────────────────────────────────────────────────────
// Forward a raw char to teleop_quest. Only r/s/f/h are real control keys.
async function sendKey(ch) {
  if (pending.value) return;
  pending.value = true;
  try {
    const r = await conn.sendTeleopKey(ch);
    if (!r.ok) conn.lastError = `Teleop key '${ch}' failed: ${r.error}`;
  } finally {
    pending.value = false;
  }
}

// Brief "SAVED: <task>" flash on the status pill after a successful S press.
const savedFlash = ref('');
let savedFlashTimer = null;
function flashSaved(text) {
  savedFlash.value = `SAVED: ${text}`;
  if (savedFlashTimer) clearTimeout(savedFlashTimer);
  savedFlashTimer = setTimeout(() => { savedFlash.value = ''; }, 1800);
}

// The actual save action — push the (already-set) current instruction up to
// teleop_quest just before firing S so a freshly-edited task is guaranteed
// applied even if the modal's set request was somehow dropped.
async function doSave() {
  const task = (currentInstruction.value || '').trim();
  if (task) await conn.sendTeleopInstruction(task);
  const r = await sendKey('s');
  if (task) flashSaved(task);
  return r;
}

// Operator pressed/clicked a UI key — route q to graceful stop and forward
// the real control chars (r/s/f) to teleop_quest.
async function onKey(ch) {
  if (ch === 'q') {
    if (pending.value) return;
    pending.value = true;
    try {
      const r = await conn.stopTeleop();
      if (!r.ok) conn.lastError = `Stop teleop failed: ${r.error}`;
    } finally {
      pending.value = false;
    }
    return;
  }
  if (ch === 's') {
    // No task set → open modal, save continues automatically once SET clicked.
    if (!currentInstruction.value.trim()) {
      pendingSaveAfterSet = true;
      instructionModalOpen.value = true;
      return;
    }
    await doSave();
    return;
  }
  if (['r', 'f'].includes(ch)) {
    await sendKey(ch);
  }
}

function onDismiss() { conn.teleopOverlayDismissed = true; }

// ── global keyboard handler ─────────────────────────────────────
function onWindowKey(e) {
  if (!visible.value) return;
  // Don't steal text-input keystrokes when the user is typing in a field.
  const t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;

  const k = e.key.toLowerCase();
  if (['r', 's', 'f', 'q'].includes(k)) {
    e.preventDefault();
    onKey(k);
  } else if (e.key === 'Escape') {
    // Esc = dismiss overlay (NOT quit teleop). Use Q for actual quit.
    onDismiss();
  }
}
onMounted(() => window.addEventListener('keydown', onWindowKey));
onUnmounted(() => window.removeEventListener('keydown', onWindowKey));
</script>

<style scoped>
.to-backdrop {
  position: fixed; inset: 0; z-index: 9500;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(ellipse at center, rgba(8, 30, 40, 0.92) 0%, rgba(0, 0, 0, 0.96) 75%);
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.to-scanlines {
  position: absolute; inset: 0; pointer-events: none;
  background: repeating-linear-gradient(
    0deg,
    rgba(255, 176, 32, 0.04) 0px,
    rgba(255, 176, 32, 0.04) 1px,
    transparent 1px, transparent 3px
  );
}

.to-card {
  position: relative;
  width: min(1600px, 97vw);
  max-height: 96vh;
  background: linear-gradient(180deg, #0a1812, #06080b);
  border: 2px solid #ffb020;
  border-radius: 8px;
  box-shadow:
    0 0 64px rgba(255, 176, 32, 0.4),
    0 0 120px rgba(255, 140, 32, 0.16),
    0 1px 0 rgba(255, 255, 255, 0.04) inset;
  color: #ffb020;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.to-phase-rec .to-card    { border-color: #ff5050; box-shadow: 0 0 70px rgba(255,80,80,0.45); }
.to-phase-prompt .to-card { border-color: #ffd060; }

/* ── header ── */
.to-head {
  display: flex; align-items: center; gap: 14px;
  padding: 16px 22px;
  background: linear-gradient(90deg, #3a2810, #1a1106);
  border-bottom: 1px solid rgba(255, 176, 32, 0.4);
}
.to-led {
  width: 16px; height: 16px; border-radius: 50%;
  background: #ffb020; box-shadow: 0 0 12px #ffb020, 0 0 3px #fff inset;
  flex-shrink: 0; animation: to-blink 1.2s steps(2, end) infinite;
}
.to-led-rec { background: #ff3030; box-shadow: 0 0 16px #ff3030, 0 0 3px #fff inset; animation: to-blink 0.55s steps(2, end) infinite; }
.to-title {
  font-weight: 900; font-size: 24px; letter-spacing: 3px;
  text-shadow: 0 0 8px rgba(255, 176, 32, 0.6);
}
.to-statpill {
  margin-left: auto;
  padding: 5px 12px;
  border: 1px solid #5a4214;
  border-radius: 2px;
  font-size: 16.5px; letter-spacing: 2px; font-weight: 700;
  background: #06080b;
  color: #ffb020;
}
.to-statpill.sp-rec { color: #ff5050; border-color: #ff5050; animation: to-blink 0.8s steps(2, end) infinite; }
.to-statpill.sp-prompt { color: #ffd060; border-color: #ffd060; }
.to-statpill.sp-ready { color: #69d180; border-color: #5a8a64; }
.to-statpill.sp-saved {
  color: #69d180; border-color: #69d180;
  background: linear-gradient(180deg, #0a2a14, #052010);
  box-shadow: 0 0 14px rgba(105, 209, 128, 0.55);
  animation: to-saved-glow 1.8s ease-out;
  max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
@keyframes to-saved-glow {
  0%   { box-shadow: 0 0 24px rgba(105, 209, 128, 0.85); }
  100% { box-shadow: 0 0 0  rgba(105, 209, 128, 0.0); }
}

/* TASK pill — sits between the title and status pill. Click anywhere on
   it to open the SaveInstructionModal. Empty state blinks amber so it's
   noticed before the first save. */
.to-taskpill {
  display: flex; align-items: center; gap: 8px;
  margin-left: 8px;
  padding: 6px 12px;
  background: linear-gradient(180deg, #1a1106, #06080b);
  border: 1px solid #5a4214;
  border-radius: 3px;
  color: #c69a4a;
  font-family: inherit;
  font-size: 17.2px;
  letter-spacing: 0.8px;
  cursor: pointer;
  transition: all 0.15s;
  max-width: 360px;
}
.to-taskpill:hover {
  border-color: #ffb020;
  color: #ffb020;
  box-shadow: 0 0 12px rgba(255, 176, 32, 0.35);
  background: linear-gradient(180deg, #3a2810, #1a1106);
}
.to-taskpill.tp-empty {
  border-style: dashed;
  border-color: rgba(255, 176, 32, 0.55);
  color: #ffd060;
  animation: to-blink 1.4s steps(2, end) infinite;
}
.tp-glyph { font-size: 18px; color: #ffb020; flex-shrink: 0; }
.tp-key {
  font-size: 15px; font-weight: 800;
  letter-spacing: 1.6px;
  color: #997040;
  flex-shrink: 0;
}
.to-taskpill:hover .tp-key { color: #ffb020; }
.tp-sep { color: rgba(255, 176, 32, 0.3); flex-shrink: 0; }
.tp-text {
  font-weight: 600;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tp-edit {
  font-size: 18px;
  opacity: 0.65;
  flex-shrink: 0;
}
.to-taskpill:hover .tp-edit { opacity: 1; }

/* ── camera grid ── */
.to-cams {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
  padding: 14px 18px 6px;
  flex-shrink: 1;
}
.to-cam-tile {
  background: #06080b;
  border: 1px solid rgba(255, 176, 32, 0.28);
  border-radius: 4px;
  overflow: hidden;
  display: flex; flex-direction: column;
}
.to-cam-label {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 10px;
  background: linear-gradient(90deg, #1a1106, #06080b);
  border-bottom: 1px solid rgba(255, 176, 32, 0.2);
  font-size: 15.8px; letter-spacing: 2px; color: #c69a4a;
}
.to-cam-led {
  width: 7px; height: 7px; border-radius: 50%;
  background: #5a4214;
}
.to-cam-led.on {
  background: #69d180; box-shadow: 0 0 6px #69d180;
  animation: to-blink 1.2s steps(2, end) infinite;
}
.to-cam-view {
  aspect-ratio: 16 / 11;
  background: #04060a;
  display: flex; align-items: center; justify-content: center;
}
.to-cam-img {
  width: 100%; height: 100%; object-fit: contain;
}
.to-cam-empty {
  font-size: 16.5px; letter-spacing: 1.5px; color: #5a4214; font-style: italic;
}

/* ── action buttons ── */
.to-actions {
  display: flex; gap: 10px;
  padding: 8px 18px 4px;
}
.to-btn {
  flex: 1;
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 14px 16px;
  border: 1px solid #5a4214;
  background: #06080b;
  color: #ffb020;
  font-family: inherit;
  font-weight: 800; letter-spacing: 1.5px; font-size: 18px;
  cursor: pointer; border-radius: 3px;
  transition: all 0.15s;
}
.to-btn:hover:not(:disabled) { background: #1a1106; box-shadow: 0 0 14px rgba(255, 176, 32, 0.35); }
.to-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.to-btn-key {
  background: #1a1106; padding: 2px 7px; border-radius: 2px;
  font-size: 16.5px; color: #ffd060; border: 1px solid #5a4214;
  letter-spacing: 1.5px;
}
.to-btn-rec  { border-color: #ff5050; color: #ff8080; }
.to-btn-rec:hover:not(:disabled) { box-shadow: 0 0 16px rgba(255, 80, 80, 0.5); background: #2a0a0a; }
.to-btn-rec.active { background: linear-gradient(180deg, #5a0a0a, #2a0606); color: #ff9090; border-color: #ff5050; }
.to-btn-save { border-color: #69d180; color: #89e190; }
.to-btn-save:hover:not(:disabled) { box-shadow: 0 0 16px rgba(105, 209, 128, 0.45); background: #0a2a14; }
.to-btn-discard { border-color: #d06090; color: #f080b0; }
.to-btn-discard:hover:not(:disabled) { box-shadow: 0 0 16px rgba(208, 96, 144, 0.5); background: #2a0a1a; }
.to-btn-quit { border-color: #ff8030; color: #ffa060; }
.to-btn-quit:hover:not(:disabled) { box-shadow: 0 0 16px rgba(255, 128, 48, 0.45); background: #2a1408; }

/* ── prompt row (only when teleop is asking y/n) ── */
.to-prompt {
  display: flex; align-items: center; gap: 12px;
  margin: 8px 18px 4px;
  padding: 12px 16px;
  background: rgba(255, 208, 96, 0.08);
  border: 1px solid #ffd060;
  border-radius: 4px;
  animation: to-pulse 1.4s ease-in-out infinite;
}
.to-prompt-label {
  font-size: 19.5px; font-weight: 800; letter-spacing: 1.5px;
  color: #ffd060; text-shadow: 0 0 6px rgba(255, 208, 96, 0.6);
}
.to-prompt-btn {
  margin-left: auto;
  padding: 10px 16px;
  border: 1px solid #5a4214;
  background: #06080b;
  color: #ffd060;
  font-family: inherit; font-weight: 800; letter-spacing: 1.5px; font-size: 17.2px;
  border-radius: 3px; cursor: pointer; transition: all 0.15s;
}
.to-prompt-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.to-prompt-yes { border-color: #69d180; color: #89e190; }
.to-prompt-no  { border-color: #ff8030; color: #ffa060; }
.to-prompt-yes:hover:not(:disabled) { box-shadow: 0 0 12px rgba(105, 209, 128, 0.5); }
.to-prompt-no:hover:not(:disabled)  { box-shadow: 0 0 12px rgba(255, 128, 48, 0.5); }

/* ── footer meter ── */
.to-foot {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 18px 12px;
  border-top: 1px solid rgba(255, 176, 32, 0.18);
}
.to-meter {
  display: flex; align-items: center; gap: 8px;
  font-size: 16.5px; letter-spacing: 1.5px;
  color: #c69a4a;
  flex: 1;
  flex-wrap: wrap;
}
.to-meter-led {
  width: 8px; height: 8px; border-radius: 50%;
  background: #69d180; box-shadow: 0 0 6px #69d180;
  animation: to-blink 1.3s steps(2, end) infinite;
}
.to-meter-label { color: #997040; }
.to-meter-value { color: #ffb020; font-weight: 700; font-variant-numeric: tabular-nums; }
.to-meter-sep { color: rgba(255, 176, 32, 0.3); padding: 0 2px; }

.to-dismiss {
  padding: 8px 14px;
  border: 1px solid #5a4214; background: #06080b;
  color: #c69a4a;
  font-family: inherit; font-weight: 800; letter-spacing: 1.5px; font-size: 15.8px;
  cursor: pointer; border-radius: 3px;
  transition: all 0.15s;
}
.to-dismiss:hover { background: #1a1106; color: #ffb020; box-shadow: 0 0 10px rgba(255, 176, 32, 0.3); }

.to-error {
  margin: 0 18px 12px;
  padding: 8px 12px;
  background: rgba(255, 64, 32, 0.12);
  border: 1px solid rgba(255, 64, 32, 0.5);
  border-radius: 3px;
  color: #ff8c20; font-size: 16.5px;
}

/* ── animations ── */
@keyframes to-blink { 50% { opacity: 0.35; } }
@keyframes to-pulse {
  0%, 100% { box-shadow: 0 0 8px rgba(255, 208, 96, 0.2); }
  50%      { box-shadow: 0 0 22px rgba(255, 208, 96, 0.55); }
}

.to-fade-enter-active, .to-fade-leave-active { transition: opacity 0.22s ease; }
.to-fade-enter-from, .to-fade-leave-to { opacity: 0; }
.to-fade-enter-active .to-card,
.to-fade-leave-active .to-card { transition: transform 0.28s cubic-bezier(0.2, 0.8, 0.2, 1); }
.to-fade-enter-from .to-card, .to-fade-leave-to .to-card { transform: scale(0.96); }
.to-fade-leave-active .to-backdrop,
.to-fade-leave-to .to-backdrop { pointer-events: none; }
</style>
