<template>
  <div>
    <!-- Icon Panel -->
    <div class="icon-panel">
      <!-- 假设有一个默认图标，这里用占位符 -->
      <div class="panel-icon-placeholder"></div>
    </div>

    <!-- Camera Feed -->
    <div class="floating-panel camera-panel">
      <div class="panel-header">
        <CameraIcon />
        <span>{{ label }}</span>
      </div>

      <div class="camera-feed">
        <img v-if="imageUrl" :src="imageUrl" class="feed-image" alt="Live Feed" />
        <div v-else class="no-signal">
          <span>NO SIGNAL</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import CameraIcon from '@/components/icons/CameraIcon.vue';

defineProps({
  imageUrl: { type: String, default: null },
  label: { type: String, default: 'Camera (RGB)' },
  // Slot positions, all anchored to the LEFT side, stacking from top:
  //   'top'    = row 0 (1rem)
  //   'bottom' = row 1 (290px)
  //   'lower'  = row 2 (580px)
  position: { type: String, default: 'top' }
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
  object-fit: cover;
  display: block;
}

.no-signal {
  color: #555;
  font-family: monospace;
  font-size: 14px;
  letter-spacing: 2px;
}
</style>