<template>
  <Transition name="tmb-slide">
    <div v-if="conn.teachActive" class="tmb-banner">
      <span class="tmb-led" />
      <span class="tmb-label">PROGRAMMING MODE</span>
      <span class="tmb-text">arms are compliant — hand-guide them, then return to EXECUTION</span>
      <button class="tmb-exit" @click="conn.exitTeach()" title="Stop floating, hold pose, resume control">
        EXIT → HOLD POSE
      </button>
    </div>
  </Transition>
</template>

<script setup>
import { useConnectionStore } from '@/stores/connection';
const conn = useConnectionStore();
</script>

<style scoped>
.tmb-banner {
  position: absolute;
  top: 102px;
  left: 1.5rem; right: 1.5rem;
  z-index: 160;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 16px;
  border-radius: 6px;
  background: linear-gradient(180deg, #2a1c08, #140d04);
  border: 1px solid rgba(255, 176, 32, 0.65);
  box-shadow: 0 0 22px rgba(255, 176, 32, 0.28), 0 6px 18px rgba(0, 0, 0, 0.45);
  color: #ffb020;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.tmb-led {
  width: 11px; height: 11px; border-radius: 50%;
  background: #ffb020;
  box-shadow: 0 0 10px #ffb020;
  flex-shrink: 0;
  animation: tmb-pulse 1.2s ease-in-out infinite;
}
@keyframes tmb-pulse { 50% { opacity: 0.4; } }
.tmb-label {
  font-weight: 800;
  letter-spacing: 1.8px;
  font-size: 17px;
  text-shadow: 0 0 8px rgba(255, 176, 32, 0.5);
}
.tmb-text {
  font-size: 16px;
  color: #d9b66a;
  letter-spacing: 0.3px;
}
.tmb-exit {
  margin-left: auto;
  padding: 7px 14px;
  border: 1px solid #ff8c20;
  border-radius: 3px;
  background: #06080b;
  color: #ff8c20;
  font-family: inherit;
  font-weight: 700;
  letter-spacing: 1px;
  font-size: 15.5px;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}
.tmb-exit:hover { background: #2a1c08; box-shadow: 0 0 14px rgba(255, 140, 32, 0.5); }

.tmb-slide-enter-active, .tmb-slide-leave-active { transition: opacity 0.18s ease, transform 0.18s ease; }
.tmb-slide-enter-from, .tmb-slide-leave-to { opacity: 0; transform: translateY(-12px); }
</style>
