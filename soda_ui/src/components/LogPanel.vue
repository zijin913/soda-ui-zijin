<template>
  <div v-if="conn.launcher === 'up'" class="lp-wrap" :class="{ 'lp-collapsed': collapsed }">
    <header class="lp-head" @click="toggleCollapsed">
      <span class="lp-led" :class="{ 'lp-led-err': hasFreshError }" />
      <span class="lp-title">LOG</span>
      <span class="lp-tag lp-tag-be" :class="{ on: showBe }"
            @click.stop="showBe = !showBe"
            title="Toggle backend stream">BE</span>
      <span class="lp-tag lp-tag-hw" :class="{ on: showHw }"
            @click.stop="showHw = !showHw"
            title="Toggle hardware stream">HW</span>
      <span v-if="hasTele" class="lp-tag lp-tag-tele" :class="{ on: showTele }"
            @click.stop="showTele = !showTele"
            title="Toggle teleop stream">TELE</span>
      <span v-if="hasCalib" class="lp-tag lp-tag-calib" :class="{ on: showCal }"
            @click.stop="showCal = !showCal"
            title="Toggle calibration stream">CAL</span>
      <span v-if="hasPolicy" class="lp-tag lp-tag-policy" :class="{ on: showPol }"
            @click.stop="showPol = !showPol"
            title="Toggle policy stream">POL</span>
      <span class="lp-count">{{ mergedLines.length }} lines</span>
      <span v-if="conn.lastEvent" class="lp-event">{{ conn.lastEvent }}</span>
      <span class="lp-toggle">{{ collapsed ? '▴' : '▾' }}</span>
    </header>

    <div v-show="!collapsed" ref="bodyRef" class="lp-body">
      <div v-if="!mergedLines.length" class="lp-empty">(no output yet)</div>
      <div v-for="(row, i) in mergedLines" :key="i"
           :class="['lp-row', `lp-kind-${row.kind}`]">
        <span :class="['lp-rtag', `lp-rtag-${row.stream}`]">[{{ row.stream }}]</span>
        <span class="lp-rtext">{{ row.text }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useConnectionStore } from '@/stores/connection';

const conn = useConnectionStore();
const collapsed = ref(false);
const showBe = ref(true);
const showHw = ref(true);
// Per-feature streams — toggles default on; the tags only render while the
// feature is active or has produced output (see hasTele/hasCalib/hasPolicy).
const showTele = ref(true);
const showCal = ref(true);
const showPol = ref(true);
const bodyRef = ref(null);
let stickToBottom = true;

const hasTele = computed(
  () => conn.teleopRunning || conn.featureLogs.teleop.length > 0,
);
const hasCalib = computed(
  () => conn.calibActive || conn.featureLogs.calib.length > 0,
);
const hasPolicy = computed(
  () => conn.policyActive || conn.featureLogs.policy.length > 0,
);

function toggleCollapsed() { collapsed.value = !collapsed.value; }

// Heuristic line classification — drives the color of the row body. We
// look at common markers from python loggers, uvicorn access lines, and
// our own ✓/✗ glyphs. INFO + 2xx HTTP collapse to a muted gray so the
// real signal (errors / warnings) actually stands out.
function classifyLine(text) {
  if (/✗/.test(text) || /\b(ERROR|CRITICAL|FATAL|Exception|Traceback|failed|FAIL)\b/.test(text)
      || /" (5\d\d|4\d\d) /.test(text)) {
    return 'err';
  }
  if (/⚠️|⚠/.test(text) || /\b(WARN|WARNING|deprecat)/i.test(text)) {
    return 'warn';
  }
  if (/✓/.test(text) || /\b(success|connected|READY|started)\b/i.test(text)) {
    return 'ok';
  }
  if (/\bINFO\b/.test(text) || /" 2\d\d /.test(text)) {
    return 'info';
  }
  return 'def';
}

function extractTs(text) {
  const m = /^\[(\d\d:\d\d:\d\d)\]/.exec(text);
  return m ? m[1] : '00:00:00';
}

const mergedLines = computed(() => {
  const out = [];
  const pushStream = (on, lines, tag) => {
    if (!on) return;
    for (const l of lines) {
      out.push({ stream: tag, text: l, kind: classifyLine(l), ts: extractTs(l) });
    }
  };
  pushStream(showBe.value, conn.backendLogs, 'BE');
  pushStream(showHw.value, conn.hwLogs, 'HW');
  pushStream(showTele.value, conn.featureLogs.teleop, 'TELE');
  pushStream(showCal.value, conn.featureLogs.calib, 'CAL');
  pushStream(showPol.value, conn.featureLogs.policy, 'POL');
  // Stable sort by [HH:MM:SS]. Lines without a timestamp sort to top (rare).
  out.sort((a, b) => a.ts.localeCompare(b.ts));
  return out.slice(-200);
});

// Pop the panel open the moment a feature starts, so its log is visible
// without the user having to expand it manually.
watch(
  () => [conn.teleopRunning, conn.calibActive, conn.policyActive],
  (now, prev) => {
    if (now.some((v, i) => v && !prev?.[i])) collapsed.value = false;
  },
);

// Recent-error indicator: the head LED blinks red if any error line in the
// last ~30 rows. Lets the user spot trouble even while collapsed.
const hasFreshError = computed(
  () => mergedLines.value.slice(-30).some(r => r.kind === 'err'),
);

// Auto-scroll to bottom on new lines — but only if the user hasn't scrolled
// up to read history (otherwise we'd yank them back every 2 s).
watch(() => mergedLines.value.length, async () => {
  if (!stickToBottom || collapsed.value) return;
  await nextTick();
  const el = bodyRef.value;
  if (el) el.scrollTop = el.scrollHeight;
});

function onBodyScroll() {
  const el = bodyRef.value;
  if (!el) return;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 8;
  stickToBottom = atBottom;
}

onMounted(() => {
  conn.startLogTail();
  const el = bodyRef.value;
  if (el) el.addEventListener('scroll', onBodyScroll, { passive: true });
});
onUnmounted(() => {
  // startLogTail is idempotent + LauncherCard also calls it; safe to leave
  // the timer running so logs keep flowing for whoever else needs them.
  const el = bodyRef.value;
  if (el) el.removeEventListener('scroll', onBodyScroll);
});
</script>

<style scoped>
.lp-wrap {
  position: fixed;
  left: 16px;
  bottom: 16px;
  width: 560px;
  max-width: calc(100vw - 32px);
  z-index: 140;
  background: linear-gradient(180deg, #0a1014, #06080b);
  border: 1px solid #19212b;
  border-radius: 6px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.55),
              0 0 0 1px rgba(255, 176, 32, 0.04) inset;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  color: #a0b8b0;
  overflow: hidden;
}
.lp-collapsed { box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4); }

.lp-head {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px;
  background: linear-gradient(90deg, #0e1820, #0a1014);
  border-bottom: 1px solid #19212b;
  cursor: pointer;
  user-select: none;
  font-size: 16.5px;
  letter-spacing: 1.2px;
}
.lp-collapsed .lp-head { border-bottom: none; }
.lp-head:hover { background: linear-gradient(90deg, #122230, #0e1820); }

.lp-led {
  width: 8px; height: 8px; border-radius: 50%;
  background: #69d180;
  box-shadow: 0 0 6px #69d180;
  flex-shrink: 0;
}
.lp-led-err {
  background: #ff5050;
  box-shadow: 0 0 8px #ff5050;
  animation: lp-blink 0.7s steps(2, end) infinite;
}
@keyframes lp-blink { 50% { opacity: 0.35; } }

.lp-title {
  font-weight: 800;
  color: #ffb020;
  letter-spacing: 2px;
  text-shadow: 0 0 6px rgba(255, 176, 32, 0.45);
}
.lp-tag {
  padding: 2px 7px;
  border: 1px solid #2a3540;
  border-radius: 2px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 1px;
  color: #62717f;
  background: #06080b;
}
.lp-tag.on { color: #ffb020; border-color: rgba(255, 176, 32, 0.5); }
.lp-tag-be.on { color: #60c0d0; border-color: rgba(96, 192, 208, 0.55); }
.lp-tag-hw.on { color: #d060a0; border-color: rgba(208, 96, 160, 0.55); }
.lp-tag-tele.on   { color: #69d180; border-color: rgba(105, 209, 128, 0.55); }
.lp-tag-calib.on  { color: #b082ff; border-color: rgba(176, 130, 255, 0.55); }
.lp-tag-policy.on { color: #e0a72f; border-color: rgba(224, 167, 47, 0.55); }
.lp-tag:hover { background: #0e1820; }

.lp-count {
  font-size: 15px;
  color: #62717f;
  letter-spacing: 0.4px;
}
.lp-event {
  margin-left: auto;
  font-size: 15px;
  color: #ffb020;
  letter-spacing: 0.4px;
  text-transform: none;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lp-toggle {
  margin-left: 8px;
  font-size: 18px;
  color: #62717f;
  line-height: 1;
}
.lp-event + .lp-toggle { margin-left: 8px; }
.lp-count + .lp-toggle { margin-left: auto; }

.lp-body {
  max-height: 280px;
  overflow-y: auto;
  padding: 6px 0;
  background: #06080b;
  font-size: 18px;
  line-height: 1.45;
}
.lp-empty {
  padding: 8px 12px;
  color: #404e58;
  font-style: italic;
}
.lp-row {
  padding: 1px 12px;
  white-space: pre-wrap;
  word-break: break-word;
  display: flex;
  gap: 8px;
}
.lp-row:nth-child(odd) { background: rgba(255, 255, 255, 0.012); }

.lp-rtag {
  flex-shrink: 0;
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0.6px;
  padding-top: 2px;
}
.lp-rtag-BE { color: #60c0d0; }
.lp-rtag-HW { color: #d060a0; }
.lp-rtag-TELE { color: #69d180; }
.lp-rtag-CAL  { color: #b082ff; }
.lp-rtag-POL  { color: #e0a72f; }
.lp-rtext { flex: 1; }

/* Color coding — match terminal conventions (red = err, amber = warn,
   green = ok, muted = info). */
.lp-kind-err  .lp-rtext { color: #ff6060; }
.lp-kind-warn .lp-rtext { color: #ffb020; }
.lp-kind-ok   .lp-rtext { color: #69d180; }
.lp-kind-info .lp-rtext { color: #62717f; }
.lp-kind-def  .lp-rtext { color: #a0b8b0; }

/* Scrollbar — phosphor styling so it doesn't look out of place. */
.lp-body::-webkit-scrollbar { width: 8px; }
.lp-body::-webkit-scrollbar-track { background: #0a1014; }
.lp-body::-webkit-scrollbar-thumb {
  background: #1a2632;
  border-radius: 4px;
}
.lp-body::-webkit-scrollbar-thumb:hover { background: #2a3540; }
</style>
