<template>
  <Transition name="zg-slide">
    <button
      v-if="conn.zeroGravityActive"
      class="zg-banner phosphor"
      :title="conn.recoveryModalDismissed
        ? 'Click to re-open the recovery overlay'
        : 'Recovery overlay is open below'"
      @click="onClick"
    >
      <span class="zg-led" />
      <span class="zg-label">ZERO-GRAVITY ACTIVE — ARMS ARE FREE TO MOVE</span>
      <span class="zg-hint">
        <span v-if="conn.recoveryModalDismissed">click here to re-open recovery controls</span>
        <span v-else>push arms to <kbd>HOME</kbd>, then press <kbd>DONE</kbd> in the overlay</span>
      </span>
    </button>
  </Transition>
</template>

<script setup>
import { useConnectionStore } from '@/stores/connection';
const conn = useConnectionStore();

// Clicking the banner re-opens the RecoveryModal if it was dismissed. If the
// modal is already open this is a no-op (the modal sits on top of the banner).
const onClick = () => {
  conn.recoveryModalDismissed = false;
};
</script>

<style scoped>
.zg-banner {
  position: absolute;
  top: 102px;     /* below the 90px TopBar + 12px breathing room */
  left: 1.5rem; right: 1.5rem;
  z-index: 150;
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px;
  background: linear-gradient(90deg, #2a1c08, #1a1106);
  border: 1px solid #ffb020;
  border-radius: 6px;
  box-shadow: 0 0 24px rgba(255,176,32,0.35),
              0 1px 0 rgba(255,255,255,0.02) inset;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 18px;
  color: #ffb020;
  animation: zg-pulse 1.8s ease-in-out infinite;
  cursor: pointer;
  transition: box-shadow 0.18s ease, transform 0.18s ease;
  text-align: left;
}
.zg-banner:hover {
  box-shadow: 0 0 36px rgba(255,176,32,0.55),
              0 1px 0 rgba(255,255,255,0.04) inset;
  transform: translateY(-1px);
}
.zg-banner:active { transform: translateY(0); }
.zg-led {
  width: 14px; height: 14px; border-radius: 50%;
  background: #ffb020;
  box-shadow: 0 0 12px #ffb020, 0 0 2px #fff inset;
  flex-shrink: 0;
  animation: zg-blink 0.9s steps(2,end) infinite;
}
.zg-label {
  font-weight: 800;
  letter-spacing: 2px;
}
.zg-hint {
  margin-left: auto;
  font-size: 15.8px;
  color: #c69a4a;
  letter-spacing: 0.4px;
}
.zg-hint kbd {
  background: #06080b;
  border: 1px solid #5a4214;
  border-radius: 2px;
  padding: 1px 5px;
  margin: 0 1px;
  font-size: 15px;
  color: #ffb020;
}
@keyframes zg-pulse {
  0%, 100% { box-shadow: 0 0 12px rgba(255,176,32,0.25); }
  50%      { box-shadow: 0 0 30px rgba(255,176,32,0.55); }
}
@keyframes zg-blink { 50% { opacity: 0.4; } }

.zg-slide-enter-active, .zg-slide-leave-active { transition: all 0.25s ease; }
.zg-slide-enter-from, .zg-slide-leave-to {
  opacity: 0; transform: translateY(-12px);
}
</style>
