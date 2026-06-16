<template>
  <Transition name="hp-fade">
    <div v-if="conn.hostPolicyOpen && !conn.hostPolicyDismissed" class="hp-backdrop" @click.self="onDismiss">
      <div class="hp-modal phosphor">
        <!-- Header -->
        <header class="hp-head">
          <span class="hp-led" :class="{ live: active }" />
          <span class="hp-title">HOST POLICY</span>
          <span class="hp-phase" :class="`ph-${phase}`">{{ phaseLabel }}</span>
          <button class="hp-dismiss" @click="onDismiss"
                  title="Hide this panel — the rollout keeps running; re-open from the banner">DISMISS</button>
          <button class="hp-x" @click="onClose" title="Close (stops a running rollout)">✕</button>
        </header>

        <div class="hp-body">
          <!-- ── Left rail: per-run choices ── -->
          <section class="hp-rail">
            <label class="hp-field">
              <span class="hp-lbl">POLICY</span>
              <div class="hp-policy-row">
                <select v-model="selectedId" class="hp-select" :disabled="active">
                  <option v-for="p in policies" :key="p.id" :value="p.id">
                    {{ p.name }}{{ p.builtin ? '' : ' ✎' }}
                  </option>
                </select>
                <button class="hp-mini" :disabled="active" @click="openAdd" title="Add a new policy">＋</button>
                <button class="hp-mini" :disabled="active || !entry" @click="openEdit" title="Edit this policy">✎</button>
                <button v-if="entry && !entry.builtin" class="hp-mini" :disabled="active"
                        @click="onDeletePolicy" title="Delete this policy">🗑</button>
              </div>
            </label>

            <!-- connection facts of the selected policy (edit via ✎) -->
            <div v-if="entry" class="hp-chips">
              <span class="hp-chip">srv {{ entry.host }}:{{ entry.port }}</span>
              <span class="hp-chip">img {{ entry.image_mode }}</span>
              <span class="hp-chip">grip {{ entry.gripper_close }}</span>
              <span class="hp-chip" :class="entry.builtin ? 'built' : 'user'">{{ entry.builtin ? 'built-in' : 'user' }}</span>
            </div>

            <label class="hp-field">
              <span class="hp-lbl">PROMPT <em class="hp-sub">(this run — pick a suggestion or type)</em></span>
              <input v-model="prompt" class="hp-input" :disabled="active" list="hp-prompt-list"
                     placeholder="task instruction…" />
              <datalist id="hp-prompt-list">
                <option v-for="pr in (entry?.prompts || [])" :key="pr" :value="pr" />
              </datalist>
            </label>

            <div class="hp-field">
              <span class="hp-lbl">MODE <em class="hp-sub">(this run)</em></span>
              <div class="hp-seg">
                <button v-for="m in modes" :key="m.id" class="hp-seg-btn" :class="{ sel: mode === m.id }"
                        :disabled="active" :title="m.hint" @click="mode = m.id">{{ m.label }}</button>
              </div>
              <span class="hp-mode-hint">{{ (modes.find(m => m.id === mode) || {}).hint }}</span>
            </div>

            <label v-if="mode === 'live'" class="hp-confirm">
              <input type="checkbox" v-model="estopReady" :disabled="active" />
              <span>Hand on E-STOP — ready to run live</span>
            </label>

            <div class="hp-field">
              <span class="hp-lbl">RUN PARAMETERS
                <em class="hp-sub">{{ active ? '· smoothness/speed/latch apply live' : '· from policy, tweak per run' }}</em>
              </span>
              <div class="hp-rp">
                <label class="hp-rp-row" title="Action-chunk length the server emits (ensemble horizon). Applied at start.">
                  <span>action chunk H</span>
                  <input type="number" min="1" v-model.number="rp.chunk_h" class="hp-num" :disabled="active" />
                  <em class="hp-lock">{{ active ? 'locked' : 'start' }}</em>
                </label>
                <label class="hp-rp-row" title="Policy execution rate — keep matched to the training dt (50). Applied at start.">
                  <span>control Hz</span>
                  <input type="number" min="1" v-model.number="rp.control_hz" class="hp-num" :disabled="active" />
                  <em class="hp-lock">{{ active ? 'locked' : 'start' }}</em>
                </label>
                <label class="hp-rp-row" title="Temporal-ensemble decay. Higher = smoother but laggier action blend.">
                  <span>smoothness</span>
                  <input type="range" min="0" max="0.5" step="0.02" v-model.number="rp.ensemble_decay" />
                  <em>{{ rp.ensemble_decay }}</em>
                </label>
                <label class="hp-rp-row" title="Per-tick joint speed cap (rad). Lower = gentler/slower.">
                  <span>speed limit</span>
                  <input type="range" min="0.02" max="0.2" step="0.01" v-model.number="rp.max_joint_delta" />
                  <em>{{ rp.max_joint_delta }}</em>
                </label>
                <label class="hp-rp-row" title="Latch the gripper open/closed to stop chatter.">
                  <span>latch gripper</span>
                  <input type="checkbox" v-model="rp.binarize_gripper" />
                  <em :class="{ 'hp-live': active }">{{ active ? 'live' : '' }}</em>
                </label>
                <label class="hp-rp-row" title="Auto-stop after this many control steps (0 = run until you press STOP). Applied at start.">
                  <span>episode steps</span>
                  <input type="number" min="0" step="100" v-model.number="rp.max_steps" class="hp-num" :disabled="active" />
                  <em class="hp-lock">{{ rp.max_steps ? (active ? 'locked' : 'start') : '∞' }}</em>
                </label>
                <label class="hp-rp-row" title="Save the model-view video + tracking.csv for this rollout to output/policy_runs/.">
                  <span>record run</span>
                  <input type="checkbox" v-model="rp.record" :disabled="active" />
                  <em class="hp-lock">start</em>
                </label>
                <label v-if="rp.record" class="hp-rp-row" title="Folder name under output/policy_runs/<policy>/. Blank = timestamp.">
                  <span>run name</span>
                  <input v-model="rp.run_name" class="hp-num hp-name" :disabled="active" placeholder="(timestamp)" />
                  <em class="hp-lock">start</em>
                </label>
              </div>
            </div>

            <div class="hp-field">
              <button class="hp-adv-toggle" @click="advOpen = !advOpen">{{ advOpen ? '▾' : '▸' }} Advanced (expert)</button>
              <div v-if="advOpen" class="hp-rp">
                <label class="hp-rp-row" title="Hardware streaming/interpolation rate between control ticks. Applied at start.">
                  <span>send Hz</span>
                  <input type="number" min="1" v-model.number="adv.send_hz" class="hp-num" :disabled="active" />
                  <em class="hp-lock">start</em>
                </label>
                <label class="hp-rp-row" title="Per-tick gripper speed cap.">
                  <span>gripper Δ cap</span>
                  <input type="number" step="0.05" v-model.number="adv.max_gripper_delta" class="hp-num" />
                  <em :class="{ 'hp-live': active }">{{ active ? 'live' : '' }}</em>
                </label>
                <label class="hp-rp-row" title="Ensemble outlier rejection threshold (rad). Applied at start.">
                  <span>reject outlier</span>
                  <input type="number" step="0.1" v-model.number="adv.reject_outlier" class="hp-num" :disabled="active" />
                  <em class="hp-lock">start</em>
                </label>
                <label class="hp-rp-row" title="Disable the 1-euro output filter entirely. Applied at start.">
                  <span>no smoothing</span>
                  <input type="checkbox" v-model="adv.no_smooth" :disabled="active" />
                  <em class="hp-lock">start</em>
                </label>
                <label class="hp-rp-row" title="1-euro min cutoff Hz (lower = smoother).">
                  <span>1€ min-cut</span>
                  <input type="number" step="0.1" v-model.number="adv.smooth_mincut" class="hp-num" :disabled="adv.no_smooth" />
                  <em :class="{ 'hp-live': active }">{{ active ? 'live' : '' }}</em>
                </label>
                <label class="hp-rp-row" title="1-euro beta (higher = less lag when fast, less smoothing).">
                  <span>1€ beta</span>
                  <input type="number" step="0.05" v-model.number="adv.smooth_beta" class="hp-num" :disabled="adv.no_smooth" />
                  <em :class="{ 'hp-live': active }">{{ active ? 'live' : '' }}</em>
                </label>
                <label class="hp-rp-row" title="Integral correction for gravity under-reach (usually off — server-side gravity comp handles it). Applied at start.">
                  <span>sag comp</span>
                  <input type="checkbox" v-model="adv.sag_comp" :disabled="active" />
                  <em class="hp-lock">start</em>
                </label>
                <label class="hp-rp-row" title="Sag integral gain.">
                  <span>sag ki</span>
                  <input type="number" step="0.01" v-model.number="adv.sag_ki" class="hp-num" :disabled="active || !adv.sag_comp" />
                  <em class="hp-lock">start</em>
                </label>
                <label class="hp-rp-row" title="Sag correction cap (rad).">
                  <span>sag cap</span>
                  <input type="number" step="0.01" v-model.number="adv.sag_cap" class="hp-num" :disabled="active || !adv.sag_comp" />
                  <em class="hp-lock">start</em>
                </label>
                <label class="hp-rp-row" title="Move-to-home duration for LIVE mode (seconds). Applied at start.">
                  <span>home secs</span>
                  <input type="number" step="0.5" v-model.number="adv.home_duration_sec" class="hp-num" :disabled="active" />
                  <em class="hp-lock">start</em>
                </label>
              </div>
            </div>

            <div v-if="message" class="hp-msg" :class="{ err: phase === 'failed' }">{{ message }}</div>
            <div class="hp-rail-spacer" />
            <div class="hp-rail-note">Server / image / gripper are policy settings — edit with ✎.</div>
          </section>

          <!-- ── Right main: what the model sees + telemetry ── -->
          <section class="hp-main">
            <div class="hp-main-bar">WHAT THE MODEL SEES <span class="hp-main-sub">(exact 224 input · {{ entry?.image_mode }})</span></div>
            <div class="hp-views">
              <figure v-for="v in views" :key="v.cam" class="hp-view">
                <img v-if="showViews" :src="viewSrc(v.cam)" class="hp-img" :alt="v.label" />
                <div v-else class="hp-img hp-img-empty">{{ phase === 'idle' ? 'press ' + startLabel : 'no signal' }}</div>
                <figcaption>{{ v.label }}</figcaption>
              </figure>
            </div>
            <div class="hp-meters">
              <div class="hp-meter"><span>infer</span><b>{{ fmt(status.infer_p50_ms) }} ms</b></div>
              <div class="hp-meter"><span>ctrl rate</span><b>{{ fmt(status.control_hz) }} Hz</b></div>
              <div class="hp-meter"><span>tremor</span><b>{{ fmt(status.tremor) }}</b></div>
              <div class="hp-meter"><span>track err</span><b>{{ fmt(status.track_err) }}</b></div>
              <div class="hp-meter"><span>ens / slack</span><b>{{ status.ens_n ?? 0 }} / {{ status.slack ?? 0 }}</b></div>
              <div class="hp-meter"><span>step</span><b>{{ status.step ?? 0 }}</b></div>
            </div>
            <div v-if="status.probe" class="hp-probe">
              probe ok — arm Δ {{ fmt(status.probe.max_arm_delta_over_chunk) }} rad ·
              grip Δ {{ fmt(status.probe.max_gripper_delta_over_chunk) }} · {{ status.probe.infer_ms }} ms · no motion
            </div>
            <div v-if="status.output_dir" class="hp-probe">⏺ recording → {{ status.output_dir }}</div>
          </section>
        </div>

        <!-- Footer -->
        <footer class="hp-foot">
          <button v-if="!active" class="hp-btn primary" :disabled="!canStart" @click="onStart">{{ startLabel }}</button>
          <button v-if="active" class="hp-btn danger" @click="onStop">STOP</button>
          <button class="hp-btn ghost" @click="onClose">CLOSE</button>
        </footer>

        <!-- Policy editor (single source of truth — add OR edit; saved server-side) -->
        <Transition name="hp-pop">
          <div v-if="formOpen" class="hp-add-pop">
            <div class="hp-srv-head">{{ editingId ? 'EDIT POLICY' : 'ADD POLICY' }} <span>saved on the server</span></div>
            <div v-if="editingBuiltin" class="hp-form-note">editing a built-in → saves your own copy that overrides it</div>
            <label class="hp-srv-row"><span>name</span>
              <input v-model="np.name" class="hp-input" placeholder="my policy" /></label>
            <label class="hp-srv-row"><span>host</span>
              <input v-model="np.host" class="hp-input" placeholder="10.0.0.x" /></label>
            <label class="hp-srv-row"><span>port</span>
              <input type="number" v-model.number="np.port" class="hp-input" /></label>
            <label class="hp-srv-row hp-srv-row-top"><span>prompts</span>
              <textarea v-model="np.prompts" class="hp-input hp-ta" placeholder="one task per line" /></label>
            <label class="hp-srv-row"><span>image</span>
              <select v-model="np.image_mode" class="hp-select sm">
                <option value="stretch43">stretch43</option>
                <option value="pad43">pad43</option>
                <option value="stretch">stretch</option>
              </select></label>
            <label class="hp-srv-row"><span>gripper close</span>
              <input type="number" step="0.01" v-model.number="np.gripper_close" class="hp-input" /></label>
            <div class="hp-form-note2">chunk / control-rate &amp; tuning are set per-run in the left panel.</div>
            <div v-if="formErr" class="hp-msg err">{{ formErr }}</div>
            <div class="hp-srv-foot">
              <button class="hp-btn ghost sm" @click="formOpen = false">CANCEL</button>
              <button class="hp-btn sm" :disabled="!np.name || !np.host || !np.port" @click="onSavePolicy">SAVE</button>
            </div>
          </div>
        </Transition>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, computed, reactive, watch } from 'vue';
import { useConnectionStore } from '@/stores/connection';

const conn = useConnectionStore();

const modes = [
  { id: 'probe', label: 'PROBE', hint: 'One inference, no motion — checks the link + what the model sees.' },
  { id: 'dry_run', label: 'DRY-RUN', hint: 'Full closed loop but never commands the arms.' },
  { id: 'live', label: 'LIVE', hint: 'Commands the arms. Hand on E-STOP.' },
];
const views = [
  { cam: 'cam_left_wrist', label: 'left wrist' },
  { cam: 'cam_high', label: 'side (cam_high)' },
  { cam: 'cam_right_wrist', label: 'right wrist' },
];

// per-run selections (NOT policy definition)
const selectedId = ref('');
const prompt = ref('');
const mode = ref('probe');
const estopReady = ref(false);
const viewNonce = ref(0);

// policy editor form (the single place that defines a policy's params)
const formOpen = ref(false);
const editingId = ref(null);
const formErr = ref('');
const np = reactive({
  name: '', host: '', port: 8001, prompts: '', image_mode: 'stretch43', gripper_close: 0.67,
});

// per-run run parameters (prefilled from the policy; soft knobs live-updatable)
const rp = reactive({
  chunk_h: 50, control_hz: 50, ensemble_decay: 0.1, max_joint_delta: 0.05, binarize_gripper: true,
  max_steps: 0, record: false, run_name: '',
});

// expert knobs (collapsed by default) — most users never touch these
const advOpen = ref(false);
const adv = reactive({
  send_hz: 250, max_gripper_delta: 0.5, reject_outlier: 0.5,
  no_smooth: false, smooth_mincut: 1.5, smooth_beta: 0.2,
  sag_comp: false, sag_ki: 0.05, sag_cap: 0.08, home_duration_sec: 4.0,
});

const policies = computed(() => conn.policyList || []);
const entry = computed(() => policies.value.find((p) => p.id === selectedId.value) || null);
const status = computed(() => conn.policyStatus || { phase: 'idle' });
const phase = computed(() => status.value.phase || 'idle');
const active = computed(() => conn.policyActive);
const message = computed(() => status.value.error || status.value.message || '');
const showViews = computed(() => conn.backend === 'up' && ['probe', 'running', 'homing'].includes(phase.value));
const editingBuiltin = computed(() => editingId.value && !!policies.value.find((p) => p.id === editingId.value && p.builtin));

const phaseLabel = computed(() => ({
  idle: 'READY', connecting: 'CONNECTING', homing: 'HOMING', probe: 'PROBING',
  running: 'RUNNING', stopped: 'STOPPED', failed: 'FAILED', done: 'DONE',
}[phase.value] || String(phase.value).toUpperCase()));
const startLabel = computed(() => ({ probe: 'PROBE', dry_run: 'DRY-RUN', live: 'RUN LIVE' }[mode.value] || 'START'));
const canStart = computed(() => conn.backend === 'up' && !!entry.value && (mode.value !== 'live' || estopReady.value));

function fmt(v) {
  if (v == null) return '—';
  return typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : v;
}
function viewSrc(cam) { return `${conn.backendUrl}/policy/view?cam=${cam}&n=${viewNonce.value}`; }

// when the selected policy changes, refresh the per-run prompt + run-params
// from its defaults (don't clobber while a rollout is live).
watch(entry, (e) => {
  if (!e) return;
  if (!prompt.value || !(e.prompts || []).includes(prompt.value)) prompt.value = (e.prompts || [''])[0];
  if (active.value) return;
  rp.chunk_h = e.info?.chunk_h ?? 50;
  rp.control_hz = e.info?.control_hz ?? e.defaults?.control_hz ?? 50;
  rp.ensemble_decay = e.defaults?.ensemble_decay ?? 0.1;
  rp.max_joint_delta = e.defaults?.max_joint_delta ?? 0.05;
  rp.binarize_gripper = e.defaults?.binarize_gripper ?? true;
  const d = e.defaults || {};
  adv.send_hz = d.send_hz ?? 250;
  adv.max_gripper_delta = d.max_gripper_delta ?? 0.5;
  adv.reject_outlier = d.reject_outlier ?? 0.5;
  adv.no_smooth = d.no_smooth ?? false;
  adv.smooth_mincut = d.smooth_mincut ?? 1.5;
  adv.smooth_beta = d.smooth_beta ?? 0.2;
  adv.sag_comp = d.sag_comp ?? false;
});

// push soft-knob changes to a live rollout (debounced); structural params
// (chunk_h, control_hz) only apply at the next start.
let _rpTimer = null;
watch(() => [rp.ensemble_decay, rp.max_joint_delta, rp.binarize_gripper,
             adv.smooth_mincut, adv.smooth_beta, adv.max_gripper_delta], () => {
  if (!active.value) return;
  if (_rpTimer) clearTimeout(_rpTimer);
  _rpTimer = setTimeout(() => {
    conn.updatePolicyParams({
      ensemble_decay: rp.ensemble_decay, max_joint_delta: rp.max_joint_delta, binarize_gripper: rp.binarize_gripper,
      smooth_mincut: adv.smooth_mincut, smooth_beta: adv.smooth_beta, max_gripper_delta: adv.max_gripper_delta,
    });
  }, 150);
});

// ── run (per-run choices; structural params from rp, rest from the policy) ──
async function onStart() {
  const overrides = {
    chunk_h: rp.chunk_h, control_hz: rp.control_hz, ensemble_decay: rp.ensemble_decay,
    max_joint_delta: rp.max_joint_delta, binarize_gripper: rp.binarize_gripper, max_steps: rp.max_steps,
    record: rp.record, run_name: rp.run_name,
    send_hz: adv.send_hz, max_gripper_delta: adv.max_gripper_delta, reject_outlier: adv.reject_outlier,
    no_smooth: adv.no_smooth, smooth_mincut: adv.smooth_mincut, smooth_beta: adv.smooth_beta,
    sag_comp: adv.sag_comp, sag_ki: adv.sag_ki, sag_cap: adv.sag_cap, home_duration_sec: adv.home_duration_sec,
  };
  const r = await conn.startPolicy({ policy_id: selectedId.value, prompt: prompt.value, mode: mode.value, overrides });
  if (!r.ok) conn.lastError = `Policy start failed: ${r.error}`;
  else viewNonce.value++;
}
async function onStop() { await conn.stopPolicy(); }
function onDismiss() { conn.dismissHostPolicy(); }
async function onClose() {
  if (active.value) await conn.stopPolicy();
  conn.closeHostPolicy();
}

// ── policy editor (add / edit — the only place these params are set) ──
function _loadForm(e) {
  np.name = e?.name || '';
  np.host = e?.host || '';
  np.port = e?.port ?? 8001;
  np.prompts = (e?.prompts || []).join('\n');
  np.image_mode = e?.image_mode || 'stretch43';
  np.gripper_close = e?.gripper_close ?? 0.67;
}
function openAdd() {
  formErr.value = '';
  editingId.value = null;
  _loadForm(null);
  if (entry.value) { np.host = entry.value.host || ''; np.port = entry.value.port ?? 8001; }  // convenience seed
  formOpen.value = true;
}
function openEdit() {
  if (!entry.value) return;
  formErr.value = '';
  editingId.value = entry.value.id;
  _loadForm(entry.value);
  formOpen.value = true;
}
async function onSavePolicy() {
  formErr.value = '';
  const body = {
    name: np.name, type: 'openpi_ws', host: np.host, port: np.port,
    prompts: np.prompts.split('\n').map((s) => s.trim()).filter(Boolean),
    image_mode: np.image_mode, gripper_close: np.gripper_close,
  };
  if (editingId.value) body.id = editingId.value;  // edit (built-in -> override under same id)
  const r = await conn.savePolicy(body);
  if (!r.ok) { formErr.value = r.error || 'save failed'; return; }
  formOpen.value = false;
  if (r.id) selectedId.value = r.id;
}
async function onDeletePolicy() {
  if (!entry.value || entry.value.builtin) return;
  const r = await conn.deletePolicy(selectedId.value);
  if (!r.ok) { conn.lastError = `Delete failed: ${r.error}`; return; }
  selectedId.value = policies.value.length ? policies.value[0].id : '';
}

// lifecycle: fetch registry + poll + status ws while the modal is open.
watch(() => conn.hostPolicyOpen, async (open) => {
  if (open) {
    await conn.fetchPolicyList();
    if (!selectedId.value && policies.value.length) selectedId.value = policies.value[0].id;
    conn.startPolicyPolling();
    conn.openPolicyWs();
    viewNonce.value++;
  } else {
    conn.stopPolicyPolling();
    conn.closePolicyWs();
    formOpen.value = false;
  }
}, { immediate: true });

function onKey(e) { if (e.key === 'Escape') { if (formOpen.value) formOpen.value = false; else onDismiss(); } }
watch(() => conn.hostPolicyOpen, (o) => {
  if (o) window.addEventListener('keydown', onKey);
  else window.removeEventListener('keydown', onKey);
});
</script>

<style scoped>
.hp-backdrop {
  position: fixed; inset: 0; z-index: 10200;
  background: rgba(0, 0, 0, 0.7); backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center;
}
.hp-modal {
  position: relative;
  width: 90vw; height: 88vh;
  display: flex; flex-direction: column;
  background: linear-gradient(180deg, #1a1206, #0a0806);
  border: 1px solid #ffb347; border-radius: 8px;
  box-shadow: 0 0 36px rgba(255, 179, 71, 0.3), 0 1px 0 rgba(255,255,255,0.03) inset;
  color: #ffe6c2;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 14px;
}
.hp-head {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 18px; border-bottom: 1px solid #4a3414; flex-shrink: 0;
}
.hp-led { width: 14px; height: 14px; border-radius: 50%; background: #5a4214; box-shadow: 0 0 10px rgba(255,179,71,.4); }
.hp-led.live { background: #ffb347; box-shadow: 0 0 12px #ffb347, 0 0 2px #fff inset; animation: hp-blink 1s steps(2,end) infinite; }
.hp-title { font-weight: 800; letter-spacing: 2px; font-size: 16px; }
.hp-phase { font-size: 13px; letter-spacing: 1px; color: #ffd28a; padding: 2px 8px; border: 1px solid #5a4214; border-radius: 2px; background: #06080b; }
.hp-phase.ph-running, .hp-phase.ph-probe { color: #8ff0a0; border-color: #2e6b3a; }
.hp-phase.ph-failed { color: #ff8a7a; border-color: #6b2e2e; }
.hp-dismiss, .hp-x { background: #06080b; color: #c69a4a; border: 1px solid #5a4214; border-radius: 3px; padding: 4px 8px; font-size: 13px; cursor: pointer; }
.hp-dismiss { margin-left: auto; }
.hp-x { margin-left: 8px; }
.hp-dismiss:hover, .hp-x:hover { border-color: #ffb347; color: #ffe6c2; }

.hp-body { flex: 1 1 auto; min-height: 0; display: flex; gap: 0; }
.hp-rail {
  flex: 0 0 400px; overflow-y: auto;
  display: flex; flex-direction: column; gap: 14px;
  padding: 18px 18px; border-right: 1px solid #3a2c14;
}
.hp-rail-spacer { flex: 1; }
.hp-rail-note { font-size: 12px; color: #7c5e2a; }
.hp-main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 12px; padding: 16px 18px; }
.hp-main-bar { font-size: 13px; letter-spacing: 1.5px; color: #c69a4a; flex-shrink: 0; }
.hp-main-sub { color: #7c5e2a; }

.hp-field { display: flex; flex-direction: column; gap: 5px; }
.hp-lbl { font-size: 12.5px; letter-spacing: 1.5px; color: #c69a4a; }
.hp-sub { color: #7c5e2a; font-style: normal; letter-spacing: 0.5px; }
.hp-select, .hp-input { background: #06080b; color: #ffe6c2; border: 1px solid #5a4214; border-radius: 4px; padding: 7px 9px; font-size: 15px; font-family: inherit; width: 100%; }
.hp-select.sm { padding: 3px 6px; font-size: 14px; width: auto; }
.hp-select:focus, .hp-input:focus { outline: none; border-color: #ffb347; }

.hp-policy-row { display: flex; gap: 6px; align-items: center; }
.hp-policy-row .hp-select { flex: 1; }
.hp-mini { background: #06080b; color: #c69a4a; border: 1px solid #5a4214; border-radius: 4px; padding: 7px 10px; font-size: 15px; line-height: 1; cursor: pointer; }
.hp-mini:hover:not(:disabled) { border-color: #ffb347; color: #ffe6c2; }
.hp-mini:disabled { opacity: 0.5; cursor: default; }
.hp-add-pop {
  position: absolute; left: 14px; top: 70px; z-index: 6;
  width: 340px; max-height: 82vh; overflow-y: auto;
  display: flex; flex-direction: column; gap: 8px;
  background: linear-gradient(180deg, #221708, #0c0906);
  border: 1px solid #ffb347; border-radius: 6px; padding: 12px;
  box-shadow: 0 8px 28px rgba(0,0,0,0.55), 0 0 18px rgba(255,179,71,0.25);
}
.hp-form-note { font-size: 12px; color: #ffd28a; }
.hp-form-sec { font-size: 11.5px; letter-spacing: 1px; color: #8a6a30; margin-top: 4px; border-top: 1px solid #3a2c14; padding-top: 6px; }
.hp-srv-row-top { align-items: start; }
.hp-ta { min-height: 56px; resize: vertical; }

.hp-rp { display: flex; flex-direction: column; gap: 10px; border: 1px solid #3a2c14; border-radius: 6px; padding: 12px; }
.hp-rp-row { display: grid; grid-template-columns: 1fr auto 56px; align-items: center; gap: 10px; font-size: 13.5px; color: #d9b878; }
.hp-rp-row input[type="range"] { width: 130px; accent-color: #ffb347; }
.hp-num { width: 84px; background: #06080b; color: #ffe6c2; border: 1px solid #5a4214; border-radius: 4px; padding: 6px 8px; font-size: 14px; font-family: inherit; }
.hp-num:disabled { opacity: 0.55; }
.hp-name { width: 150px; }
.hp-rp-row em { text-align: right; color: #ffe6c2; font-style: normal; }
.hp-lock { font-size: 11px; color: #8a6a30; }
.hp-live { color: #8ff0a0; font-size: 12px; }
.hp-form-note2 { font-size: 12px; color: #8a6a30; border-top: 1px solid #3a2c14; padding-top: 8px; }
.hp-adv-toggle { align-self: flex-start; background: none; border: none; color: #c69a4a; cursor: pointer; font-size: 13px; padding: 2px 0 8px; font-family: inherit; }
.hp-adv-toggle:hover { color: #ffe6c2; }

.hp-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.hp-chip { font-size: 12.5px; color: #b88a3a; border: 1px solid #3a2c14; border-radius: 2px; padding: 2px 7px; background: #06080b; }
.hp-chip.user { color: #8ff0a0; border-color: #2e6b3a; }
.hp-chip.built { color: #8a6a30; }

.hp-seg { display: flex; border: 1px solid #5a4214; border-radius: 4px; overflow: hidden; }
.hp-seg-btn { flex: 1; background: #06080b; color: #c69a4a; border: none; border-right: 1px solid #3a2c14; padding: 9px 0; font-size: 14px; letter-spacing: 1px; cursor: pointer; font-family: inherit; }
.hp-seg-btn:last-child { border-right: none; }
.hp-seg-btn.sel { background: linear-gradient(180deg, #6b4d14, #4a3410); color: #fff0d0; }
.hp-seg-btn:disabled { opacity: 0.5; cursor: default; }
.hp-mode-hint { font-size: 12.5px; color: #8a6a30; }

.hp-confirm { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #ffd28a; }
.hp-msg { font-size: 14px; color: #d9b878; border-left: 2px solid #5a4214; padding: 6px 10px; background: #06080b; }
.hp-msg.err { color: #ff8a7a; border-color: #6b2e2e; }

.hp-views { flex: 1 1 auto; min-height: 0; display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.hp-view { display: flex; flex-direction: column; min-height: 0; gap: 4px; }
.hp-img { flex: 1; min-height: 0; width: 100%; object-fit: contain; background: #000; border: 1px solid #3a2c14; border-radius: 4px; }
.hp-img-empty { display: flex; align-items: center; justify-content: center; color: #6b5424; font-size: 15px; letter-spacing: 1px; }
.hp-view figcaption { font-size: 13px; color: #b88a3a; text-align: center; letter-spacing: 0.5px; flex-shrink: 0; }
.hp-meters { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; flex-shrink: 0; }
.hp-meter { background: #06080b; border: 1px solid #3a2c14; border-radius: 3px; padding: 8px 10px; }
.hp-meter span { display: block; font-size: 12px; color: #b88a3a; letter-spacing: 0.5px; }
.hp-meter b { font-size: 22px; color: #ffe6c2; }
.hp-probe { font-size: 13.5px; color: #8ff0a0; background: #06080b; border: 1px solid #2e6b3a; border-radius: 3px; padding: 7px 10px; flex-shrink: 0; }

.hp-foot { display: flex; align-items: center; gap: 8px; padding: 12px 18px; border-top: 1px solid #4a3414; flex-shrink: 0; }
.hp-btn { background: #06080b; color: #ffe6c2; border: 1px solid #5a4214; border-radius: 4px; padding: 9px 18px; font-size: 15px; letter-spacing: 1px; cursor: pointer; font-family: inherit; }
.hp-btn.sm { padding: 6px 12px; font-size: 13.5px; }
.hp-btn.primary { background: linear-gradient(180deg, #ffb347, #d98e22); color: #1a1206; border-color: #ffb347; font-weight: 800; }
.hp-btn.primary:disabled { opacity: 0.45; cursor: default; }
.hp-btn.danger { color: #ff8a7a; border-color: #6b2e2e; }
.hp-btn.ghost { color: #c69a4a; }
.hp-btn:hover:not(:disabled) { filter: brightness(1.1); }

.hp-srv-head { font-size: 13px; letter-spacing: 1px; color: #ffd28a; display: flex; justify-content: space-between; align-items: baseline; }
.hp-srv-head span { font-size: 11.5px; color: #8a6a30; letter-spacing: 0; }
.hp-srv-row { display: grid; grid-template-columns: 84px 1fr; align-items: center; gap: 8px; font-size: 14px; color: #d9b878; }
.hp-srv-foot { display: flex; gap: 8px; justify-content: flex-end; margin-top: 2px; }

@keyframes hp-blink { 50% { opacity: 0.4; } }
.hp-fade-enter-active, .hp-fade-leave-active { transition: opacity .18s; }
.hp-fade-enter-from, .hp-fade-leave-to { opacity: 0; }
.hp-fade-enter-active .hp-modal, .hp-fade-leave-active .hp-modal { transition: transform .22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.hp-fade-enter-from .hp-modal, .hp-fade-leave-to .hp-modal { transform: scale(0.97); }
.hp-pop-enter-active, .hp-pop-leave-active { transition: opacity .15s, transform .15s; }
.hp-pop-enter-from, .hp-pop-leave-to { opacity: 0; transform: translateY(8px); }
</style>
