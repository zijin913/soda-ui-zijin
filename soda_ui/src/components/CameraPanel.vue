<template>
  <div>
    <!-- Icon Panel -->
    <div class="icon-panel">
      <div class="panel-icon-placeholder"></div>
    </div>

    <!-- Camera Feed -->
    <div class="floating-panel camera-panel">
      <div class="panel-header">
        <CameraIcon />
        <span>{{ label }}</span>
        <!-- Live LED — green when streaming, red dim when not. -->
        <span class="live-dot" :class="imageUrl ? 'on' : 'off'"></span>
      </div>

      <div class="camera-feed" :class="{ phosphor: !imageUrl }">
        <img v-if="imageUrl" :src="imageUrl" class="feed-image" alt="Live Feed" />
        <div v-else class="no-signal phosphor-grid">
          <div class="no-signal-content">
            <span class="ns-led" />
            <span class="ns-main">NO SIGNAL</span>
            <span class="ns-sub">{{ subLabel }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import CameraIcon from '@/components/icons/CameraIcon.vue';
import { useConnectionStore } from '@/stores/connection';

const props = defineProps({
  imageUrl: { type: String, default: null },
  label: { type: String, default: 'Camera (RGB)' },
  // Slot positions, all anchored to the LEFT side, stacking from top:
  //   'top'    = row 0 (1rem)
  //   'bottom' = row 1 (290px)
  //   'lower'  = row 2 (580px)
  position: { type: String, default: 'top' }
});

const conn = useConnectionStore();

// Sub-label explains *why* there's no signal so the user knows what to fix.
const subLabel = computed(() => {
  if (conn.launcher !== 'up') return 'launcher not reachable';
  if (conn.backend !== 'up') return 'backend offline';
  if (!conn.wsConnected) return 'ws disconnected';
  return 'awaiting first frame';
});
</script>

<style scoped>
.floating-panel {
  background: rgba(29, 29, 29, 0.9);
  border-radius: 32px;
  padding: 20px;
  backdrop-filter: blur(10px);
  z-index: 20;
}

.camera-panel {
  position: absolute;
  /* All slots anchored to left side */
  left: 1.5rem;
  right: auto;
  /* Vertical slot: 1rem / 290px / 580px (panel height ~272px + 18px gap) */
  top: v-bind("position === 'lower' ? '580px' : (position === 'bottom' ? '290px' : '1rem')");
  width: 371px;
  height: 272px;
}

.icon-panel {
  position: absolute;
  left: 30px;
  top: 12px;
  z-index: 25;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 18px;
  margin-bottom: 12px;
  color: white;
}

.camera-feed {
  width: 100%;
  height: 186px;
  background: #000;
  border-radius: 16px;
  overflow: hidden;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.feed-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

/* Header live indicator — sits to the right of the camera label. */
.live-dot {
  width: 8px; height: 8px; border-radius: 50%;
  margin-left: auto;
  background: #3b4654;
  box-shadow: 0 0 0 1px rgba(0,0,0,0.6) inset;
}
.live-dot.on  { background: #36e08a; box-shadow: 0 0 6px #36e08a; }
.live-dot.off { background: #4a1512; box-shadow: 0 0 4px rgba(255,68,56,0.45); }

/* NO SIGNAL — phosphor instrument empty state with hairline grid. */
.no-signal {
  width: 100%; height: 100%;
  background: #06080b;
  background-image:
    linear-gradient(#19212b 1px, transparent 1px),
    linear-gradient(90deg, #19212b 1px, transparent 1px);
  background-size: 22px 22px;
  display: flex; align-items: center; justify-content: center;
  position: relative;
  overflow: hidden;
}
.no-signal::after {
  /* faint scanline overlay */
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background: repeating-linear-gradient(0deg,
    rgba(255,255,255,0.025) 0px, rgba(255,255,255,0.025) 1px,
    transparent 1px, transparent 3px);
}
.no-signal-content {
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  z-index: 1;
}
.ns-led {
  width: 12px; height: 12px; border-radius: 50%;
  background: #ff4438;
  box-shadow: 0 0 10px #ff4438, 0 0 2px #fff inset;
  animation: ns-blink 1.4s steps(2,end) infinite;
}
.ns-main {
  color: #ff4438;
  font-size: 14px;
  font-weight: 800;
  letter-spacing: 3px;
  text-shadow: 0 0 8px rgba(255,68,56,0.5);
}
.ns-sub {
  color: #62717f;
  font-size: 10px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
}
@keyframes ns-blink { 50% { opacity: 0.35; } }
</style>