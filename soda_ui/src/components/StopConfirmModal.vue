<template>
  <Transition name="sc-fade">
    <div v-if="open" class="sc-backdrop" @click.self="onCancel">
      <div class="sc-modal phosphor">
        <header class="sc-head">
          <span class="sc-led" />
          <span class="sc-title">{{ isReal ? 'STOP — REAL ARMS' : 'STOP — SIMULATION' }}</span>
        </header>

        <div class="sc-body">
          <p v-if="isReal" class="sc-line">
            This stops <b>all running processes</b> and enters
            <b class="sc-warn">ZERO-GRAVITY</b> recovery.
          </p>
          <p v-else class="sc-line">
            This kills the sim and <b>all running processes</b>.
          </p>

          <ul class="sc-steps">
            <li v-if="isReal">Teleop + servers + launchers → terminated</li>
            <li v-if="isReal">Arms become free-floating (gravity-comp)</li>
            <li v-if="isReal">You'll get a recovery overlay here in the UI</li>
            <li v-else>Sim stack terminated; LauncherCard returns</li>
          </ul>

          <p v-if="isReal" class="sc-note">
            Push both arms back to <kbd>HOME</kbd> pose, then press
            <kbd>DONE</kbd> in the recovery overlay.
          </p>
        </div>

        <footer class="sc-foot">
          <button class="sc-btn sc-cancel" @click="onCancel">CANCEL</button>
          <button class="sc-btn sc-confirm" @click="onConfirm">
            {{ isReal ? 'STOP &amp; RECOVER' : 'STOP NOW' }}
          </button>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { watch, onUnmounted } from 'vue';
const props = defineProps({
  open: { type: Boolean, default: false },
  isReal: { type: Boolean, default: false },
});
const emit = defineEmits(['confirm', 'cancel']);
const onConfirm = () => emit('confirm');
const onCancel = () => emit('cancel');

// Escape key dismisses. Attach/detach the listener while open to avoid global
// listeners eating Esc when the modal isn't visible.
function onKey(e) { if (e.key === 'Escape') onCancel(); }
watch(() => props.open, (o) => {
  if (o) window.addEventListener('keydown', onKey);
  else window.removeEventListener('keydown', onKey);
});
onUnmounted(() => window.removeEventListener('keydown', onKey));
</script>

<style scoped>
.sc-backdrop {
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: rgba(0, 0, 0, 0.68);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
}
/* Don't intercept clicks during the leave animation — otherwise the modal's
   fading-out backdrop blocks the next opened modal's buttons until the
   fade completes. */
.sc-fade-leave-active .sc-backdrop,
.sc-fade-leave-to .sc-backdrop { pointer-events: none; }

.sc-modal {
  width: min(560px, 92vw);
  background: linear-gradient(180deg, #1a1106, #06080b);
  border: 1px solid #ffb020;
  border-radius: 6px;
  box-shadow:
    0 0 32px rgba(255, 176, 32, 0.35),
    0 1px 0 rgba(255, 255, 255, 0.03) inset;
  color: #ffb020;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  overflow: hidden;
}

.sc-head {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 18px;
  background: linear-gradient(90deg, #2a1c08, #1a1106);
  border-bottom: 1px solid rgba(255, 176, 32, 0.4);
}
.sc-led {
  width: 12px; height: 12px; border-radius: 50%;
  background: #ffb020;
  box-shadow: 0 0 10px #ffb020, 0 0 2px #fff inset;
  animation: sc-blink 0.9s steps(2, end) infinite;
}
.sc-title {
  font-weight: 800;
  letter-spacing: 2px;
  font-size: 19.5px;
}

.sc-body {
  padding: 18px;
  font-size: 18.8px;
  line-height: 1.6;
}
.sc-line { margin: 0 0 12px; color: #d9b66a; }
.sc-line b { color: #ffb020; }
.sc-warn { color: #ff8c20 !important; letter-spacing: 1px; }
.sc-steps {
  margin: 0 0 12px;
  padding-left: 18px;
  color: #c69a4a;
  font-size: 17.2px;
}
.sc-steps li { margin: 3px 0; }
.sc-note {
  margin: 12px 0 0;
  font-size: 16.5px;
  color: #c69a4a;
}
.sc-note kbd {
  background: #06080b;
  border: 1px solid #5a4214;
  border-radius: 2px;
  padding: 1px 5px;
  margin: 0 2px;
  font-size: 15px;
  color: #ffb020;
}

.sc-foot {
  display: flex;
  gap: 10px;
  padding: 14px 18px;
  border-top: 1px solid rgba(255, 176, 32, 0.2);
  background: rgba(0, 0, 0, 0.3);
}
.sc-btn {
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
.sc-btn:hover { background: #1a1106; box-shadow: 0 0 12px rgba(255, 176, 32, 0.4); }
.sc-cancel { color: #c69a4a; }
.sc-confirm {
  border-color: #ff8c20;
  color: #ff8c20;
  box-shadow: 0 0 8px rgba(255, 140, 32, 0.2) inset;
}
.sc-confirm:hover {
  box-shadow: 0 0 16px rgba(255, 140, 32, 0.5);
  background: #2a1c08;
}

@keyframes sc-blink { 50% { opacity: 0.4; } }

.sc-fade-enter-active, .sc-fade-leave-active { transition: opacity 0.18s ease; }
.sc-fade-enter-from, .sc-fade-leave-to { opacity: 0; }
.sc-fade-enter-active .sc-modal,
.sc-fade-leave-active .sc-modal {
  transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.sc-fade-enter-from .sc-modal,
.sc-fade-leave-to .sc-modal {
  transform: translateY(-12px) scale(0.98);
}
</style>
