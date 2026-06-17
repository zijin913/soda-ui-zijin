<template>
  <Transition name="si-fade">
    <div v-if="open" class="si-backdrop" @click.self="onCancel">
      <div class="si-card phosphor">
        <header class="si-head">
          <span class="si-led" />
          <span class="si-title">SET TASK INSTRUCTION</span>
          <span class="si-hint">Esc · cancel  ·  ⌘+Enter · set</span>
        </header>

        <div class="si-body">
          <label class="si-label">
            <span>Instruction</span>
            <span class="si-sublabel">— used for every episode in this batch until you change it.</span>
          </label>
          <textarea
            ref="taRef"
            v-model="text"
            class="si-textarea"
            placeholder="e.g. pick up the red cube from the left tray and place it in the bin"
            rows="3"
            @keydown.esc.prevent="onCancel"
            @keydown.enter.exact.meta.prevent="onSet"
            @keydown.enter.exact.ctrl.prevent="onSet"
          />

          <div v-if="recent.length" class="si-recent">
            <span class="si-recent-label">RECENT</span>
            <button
              v-for="(t, i) in recent"
              :key="i"
              type="button"
              class="si-chip"
              :title="t"
              @click="useChip(t)"
            >{{ chipPreview(t) }}</button>
          </div>
        </div>

        <footer class="si-foot">
          <button class="si-btn si-btn-cancel" type="button" @click="onCancel">CANCEL</button>
          <button class="si-btn si-btn-set" type="button" :disabled="!text.trim()" @click="onSet">
            <span class="si-btn-glyph">✓</span> SET TASK
          </button>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue';

const props = defineProps({
  open: { type: Boolean, default: false },
  initialText: { type: String, default: '' },
  recent: { type: Array, default: () => [] },
});
const emit = defineEmits(['set', 'cancel']);

const text = ref(props.initialText);
const taRef = ref(null);

watch(() => props.open, async (v) => {
  if (v) {
    text.value = props.initialText || '';
    await nextTick();
    taRef.value?.focus();
    taRef.value?.select();
  }
});

function onCancel() { emit('cancel'); }
function onSet() {
  const t = text.value.trim();
  if (!t) return;
  emit('set', t);
}
function useChip(t) { text.value = t; }
function chipPreview(t) {
  const max = 32;
  return t.length > max ? t.slice(0, max - 1) + '…' : t;
}
</script>

<style scoped>
.si-backdrop {
  position: fixed; inset: 0; z-index: 10500;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(ellipse at center, rgba(8, 30, 40, 0.85) 0%, rgba(0, 0, 0, 0.94) 75%);
  backdrop-filter: blur(2px);
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.si-card {
  width: min(640px, 92vw);
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

.si-head {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 20px;
  background: linear-gradient(90deg, #3a2810, #1a1106);
  border-bottom: 1px solid rgba(255, 176, 32, 0.4);
}
.si-led {
  width: 12px; height: 12px; border-radius: 50%;
  background: #ffb020;
  box-shadow: 0 0 10px #ffb020, 0 0 2px #fff inset;
  flex-shrink: 0;
  animation: si-blink 1.5s steps(2, end) infinite;
}
@keyframes si-blink { 50% { opacity: 0.45; } }
.si-title {
  font-weight: 900; font-size: 21px; letter-spacing: 2.5px;
  text-shadow: 0 0 8px rgba(255, 176, 32, 0.55);
}
.si-hint {
  margin-left: auto;
  font-size: 15px; letter-spacing: 0.7px;
  color: #997040; text-transform: none;
}

.si-body { padding: 16px 20px 12px; }
.si-label {
  display: block;
  font-size: 16.5px; letter-spacing: 1.5px; font-weight: 700;
  color: #c69a4a;
  margin-bottom: 8px;
}
.si-sublabel {
  font-weight: 400; letter-spacing: 0.3px; color: #886440;
  margin-left: 8px;
  font-size: 15.8px;
  text-transform: none;
}

.si-textarea {
  width: 100%;
  background: #06080b;
  border: 1px solid #5a4214;
  border-radius: 3px;
  color: #ffe0a0;
  font-family: inherit;
  font-size: 19.5px;
  line-height: 1.5;
  padding: 10px 12px;
  outline: none;
  resize: vertical;
  min-height: 64px;
  transition: border-color 0.15s, box-shadow 0.15s;
  box-sizing: border-box;
}
.si-textarea:focus {
  border-color: #ffb020;
  box-shadow: 0 0 14px rgba(255, 176, 32, 0.35);
}
.si-textarea::placeholder { color: #5a4214; font-style: italic; }

.si-recent {
  margin-top: 12px;
  display: flex; flex-wrap: wrap; gap: 6px;
  align-items: center;
}
.si-recent-label {
  font-size: 15px; letter-spacing: 1.5px; color: #886440;
  font-weight: 700;
  margin-right: 4px;
}
.si-chip {
  padding: 4px 10px;
  background: #06080b;
  border: 1px solid #5a4214;
  border-radius: 12px;
  color: #c69a4a;
  font-family: inherit;
  font-size: 16.5px;
  letter-spacing: 0.5px;
  cursor: pointer;
  transition: all 0.15s;
}
.si-chip:hover {
  background: #1a1106;
  border-color: #ffb020;
  color: #ffb020;
  box-shadow: 0 0 10px rgba(255, 176, 32, 0.25);
}

.si-foot {
  display: flex; gap: 10px;
  padding: 12px 20px 16px;
  border-top: 1px solid rgba(255, 176, 32, 0.18);
  justify-content: flex-end;
}
.si-btn {
  display: flex; align-items: center; gap: 6px;
  padding: 10px 18px;
  border: 1px solid #5a4214;
  background: #06080b;
  color: #ffb020;
  font-family: inherit;
  font-weight: 800; letter-spacing: 1.5px; font-size: 18px;
  cursor: pointer; border-radius: 3px;
  transition: all 0.15s;
}
.si-btn:hover:not(:disabled) { background: #1a1106; box-shadow: 0 0 12px rgba(255, 176, 32, 0.3); }
.si-btn:disabled { opacity: 0.35; cursor: not-allowed; }

.si-btn-cancel { color: #c69a4a; border-color: #5a4214; }
.si-btn-set    { color: #89e190; border-color: #69d180; }
.si-btn-set:hover:not(:disabled) { box-shadow: 0 0 16px rgba(105, 209, 128, 0.5); background: #0a2a14; }
.si-btn-glyph { font-size: 19.5px; }

.si-fade-enter-active, .si-fade-leave-active { transition: opacity 0.18s ease; }
.si-fade-enter-from, .si-fade-leave-to { opacity: 0; }
.si-fade-enter-active .si-card,
.si-fade-leave-active .si-card { transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.si-fade-enter-from .si-card, .si-fade-leave-to .si-card { transform: scale(0.96); }
</style>
