<template>
  <div class="timeline-container">
    <!-- Playback Controls (Centered Top) -->
    <div class="playback-controls">
      <button class="control-btn small" @click="$emit('stepBackward')">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M11 19V5L2 12L11 19Z" fill="white"/>
            <rect x="13" y="5" width="2" height="14" fill="white"/>
        </svg>
      </button>
      
      <button class="control-btn large" @click="$emit(isPlaying ? 'pause' : 'play')">
        <!-- Replay Icon (if finished) -->
        <svg v-if="isFinished" width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 5V1L7 6L12 11V7C15.31 7 18 9.69 18 13C18 16.31 15.31 19 12 19C8.69 19 6 16.31 6 13H4C4 17.42 7.58 21 12 21C16.42 21 20 17.42 20 13C20 8.58 16.42 5 12 5Z" fill="white"/>
        </svg>
        <!-- Play Icon (if paused and not finished) -->
        <svg v-else-if="!isPlaying" width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M8 5V19L19 12L8 5Z" fill="white"/>
        </svg>
        <!-- Pause Icon (if playing) -->
        <svg v-else width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="6" y="4" width="4" height="16" fill="white"/>
            <rect x="14" y="4" width="4" height="16" fill="white"/>
        </svg>
      </button>

      <button class="control-btn small" @click="$emit('stepForward')">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M13 19V5L22 12L13 19Z" fill="white"/>
            <rect x="9" y="5" width="2" height="14" fill="white"/>
        </svg>
      </button>
    </div>

    <!-- Timeline Track Row -->
    <div class="timeline-row">
      <!-- Time Display -->
      <div class="time-display">
        {{ formattedCurrentTime }} / {{ formattedTotalTime }}
      </div>

      <!-- Timeline Track & Slider -->
      <div class="timeline-track-wrapper">
        <!-- Background Track (Gray bar) -->
        <div class="track-bg"></div>

        <!-- Native Range Input for Interaction -->
        <input 
          type="range" 
          min="0" 
          :max="totalFrames - 1" 
          :value="currentFrame" 
          @input="onSeek"
          class="timeline-slider"
        />
        
        <!-- Custom Pointer (Visual only, follows slider) -->
        <div class="custom-pointer" :style="{ left: pointerPosition + '%' }">
          <div class="pointer-head"></div>
          <div class="pointer-line"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  currentFrame: { type: Number, default: 0 },
  totalFrames: { type: Number, default: 100 },
  isPlaying: { type: Boolean, default: false }
});

const emit = defineEmits(['play', 'pause', 'stepForward', 'stepBackward', 'seek']);

const isFinished = computed(() => {
  return props.totalFrames > 0 && props.currentFrame >= props.totalFrames - 1;
});

const pointerPosition = computed(() => {
  if (props.totalFrames <= 1) return 0;
  return (props.currentFrame / (props.totalFrames - 1)) * 100;
});

const formatTime = (frames) => {
  if (!frames) return '0:00';
  const totalSeconds = Math.floor(frames / 30);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
};

const formattedCurrentTime = computed(() => formatTime(props.currentFrame));
const formattedTotalTime = computed(() => formatTime(props.totalFrames));

const onSeek = (event) => {
  emit('seek', parseInt(event.target.value));
};
</script>

<style scoped>
.timeline-container {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 90px;
  background: linear-gradient(180deg, transparent, rgba(13,18,24,0.7));
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 10px;
  box-sizing: border-box;
  z-index: 100;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}

/* Controls */
.playback-controls {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: 6px;
}

.control-btn {
  background: #0a0d12;
  border: 1px solid #27323f;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: #c6d3e0;
  transition: all 0.15s;
}

.control-btn:hover {
  background: #19212b;
  border-color: #ffb020;
  color: #ffb020;
}

.control-btn.small {
  width: 30px;
  height: 30px;
}

.control-btn.large {
  width: 42px;
  height: 42px;
  background: #221808;
  border-color: #5a4214;
  color: #ffb020;
  box-shadow: 0 0 10px rgba(255,176,32,0.2);
}
.control-btn.large:hover {
  background: #3a2811;
  box-shadow: 0 0 16px rgba(255,176,32,0.4);
}

/* Timeline Row */
.timeline-row {
  width: 90%;
  display: flex;
  align-items: center;
  gap: 16px;
}

.time-display {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 12px;
  color: #c6d3e0;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.8px;
  min-width: 80px;
  text-align: right;
  white-space: nowrap;
}

/* Track Wrapper */
.timeline-track-wrapper {
  position: relative;
  flex: 1;
  height: 32px;
  display: flex;
  align-items: center;
}

/* The visual track — phosphor dark with hairline border. */
.track-bg {
  position: absolute;
  width: 100%;
  height: 6px;
  background: #06080b;
  border: 1px solid #19212b;
  border-radius: 3px;
  top: 50%;
  transform: translateY(-50%);
}

/* The actual slider (invisible but clickable) */
.timeline-slider {
  position: absolute;
  width: 100%;
  height: 100%;
  opacity: 0;
  margin: 0;
  cursor: pointer;
  z-index: 10;
}

/* Custom Pointer — phosphor amber. */
.custom-pointer {
  position: absolute;
  top: -4px;
  height: calc(100% + 4px);
  width: 13px;
  pointer-events: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  transform: translateX(-50%);
}

.pointer-head {
  width: 13px;
  height: 12px;
  background: #ffb020;
  clip-path: polygon(0 0, 100% 0, 50% 100%);
  flex-shrink: 0;
  filter: drop-shadow(0 0 4px rgba(255,176,32,0.6));
}

.pointer-line {
  width: 2px;
  flex: 1;
  background: #ffb020;
  box-shadow: 0 0 6px rgba(255,176,32,0.6);
}
</style>