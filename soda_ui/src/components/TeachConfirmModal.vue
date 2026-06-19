<template>
  <Transition name="tc-fade">
    <div v-if="conn.teachConfirmOpen" class="tc-backdrop" @click.self="onCancel">
      <div class="tc-modal">
        <header class="tc-head">
          <span class="tc-led" />
          <span class="tc-title">ENTER PROGRAMMING MODE</span>
        </header>

        <div class="tc-body">
          <p class="tc-line">
            Both arms will go <b>compliant</b> (gravity-comp freedrive) so you
            can hand-guide them.
          </p>
          <ul class="tc-steps">
            <li>Keep a hand on each arm — they may <b>sag</b> slightly</li>
            <li>Any <b>running task is paused</b> (policy / teleop) — it resumes on EXECUTION</li>
            <li>Press <kbd>EXECUTION</kbd> to hold pose and resume the task</li>
          </ul>
        </div>

        <footer class="tc-foot">
          <button class="tc-btn tc-cancel" @click="onCancel">CANCEL</button>
          <button class="tc-btn tc-confirm" @click="onConfirm">FLOAT ARMS</button>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { watch, onUnmounted } from 'vue';
import { useConnectionStore } from '@/stores/connection';

const conn = useConnectionStore();
const onConfirm = () => conn.confirmTeach();
const onCancel = () => conn.cancelTeach();

function onKey(e) { if (e.key === 'Escape') onCancel(); }
watch(() => conn.teachConfirmOpen, (o) => {
  if (o) window.addEventListener('keydown', onKey);
  else window.removeEventListener('keydown', onKey);
});
onUnmounted(() => window.removeEventListener('keydown', onKey));
</script>

<style scoped>
.tc-backdrop {
  position: fixed;
  inset: 0;
  /* Above the policy modal (10200) and the teach switch (10300) so the confirm
     is reachable when Programming barges in over an open policy/teleop panel. */
  z-index: 10400;
  background: rgba(0, 0, 0, 0.68);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
}
.tc-fade-leave-active .tc-backdrop,
.tc-fade-leave-to .tc-backdrop { pointer-events: none; }

.tc-modal {
  width: min(560px, 92vw);
  background: linear-gradient(180deg, #1a1106, #06080b);
  border: 1px solid #ffb020;
  border-radius: 6px;
  box-shadow: 0 0 32px rgba(255, 176, 32, 0.35), 0 1px 0 rgba(255, 255, 255, 0.03) inset;
  color: #ffb020;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  overflow: hidden;
}

.tc-head {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 18px;
  background: linear-gradient(90deg, #2a1c08, #1a1106);
  border-bottom: 1px solid rgba(255, 176, 32, 0.4);
}
.tc-led {
  width: 12px; height: 12px; border-radius: 50%;
  background: #ffb020;
  box-shadow: 0 0 10px #ffb020, 0 0 2px #fff inset;
  animation: tc-blink 0.9s steps(2, end) infinite;
}
.tc-title { font-weight: 800; letter-spacing: 2px; font-size: 19.5px; }

.tc-body { padding: 18px; font-size: 18.8px; line-height: 1.6; }
.tc-line { margin: 0 0 12px; color: #d9b66a; }
.tc-line b { color: #ffb020; }
.tc-steps { margin: 0; padding-left: 18px; color: #c69a4a; font-size: 17.2px; }
.tc-steps li { margin: 3px 0; }
.tc-steps b { color: #ff8c20; }
.tc-steps kbd {
  background: #06080b;
  border: 1px solid #5a4214;
  border-radius: 2px;
  padding: 1px 5px;
  font-size: 15px;
  color: #69d180;
}

.tc-foot {
  display: flex;
  gap: 10px;
  padding: 14px 18px;
  border-top: 1px solid rgba(255, 176, 32, 0.2);
  background: rgba(0, 0, 0, 0.3);
}
.tc-btn {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid #5a4214;
  background: #06080b;
  color: #ffb020;
  font-family: inherit;
  font-weight: 700;
  letter-spacing: 1.5px;
  font-size: 17.2px;
  cursor: pointer;
  border-radius: 3px;
  transition: all 0.15s;
}
.tc-btn:hover { background: #1a1106; box-shadow: 0 0 12px rgba(255, 176, 32, 0.4); }
.tc-cancel { color: #c69a4a; }
.tc-confirm {
  border-color: #ff8c20;
  color: #ff8c20;
  box-shadow: 0 0 8px rgba(255, 140, 32, 0.2) inset;
}
.tc-confirm:hover { box-shadow: 0 0 16px rgba(255, 140, 32, 0.5); background: #2a1c08; }

@keyframes tc-blink { 50% { opacity: 0.4; } }
.tc-fade-enter-active, .tc-fade-leave-active { transition: opacity 0.18s ease; }
.tc-fade-enter-from, .tc-fade-leave-to { opacity: 0; }
</style>
