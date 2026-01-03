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
  height: 140px; /* Reduced height since markers are gone */
  background: #303130;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 16px;
  box-sizing: border-box;
  z-index: 100;
}

/* Controls */
.playback-controls {
  display: flex;
  align-items: center;
  gap: 24px;
  margin-bottom: 16px;
}

.control-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  transition: background 0.2s;
}

.control-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.control-btn.small {
  width: 32px;
  height: 32px;
}

.control-btn.large {
  width: 48px;
  height: 48px;
  background: rgba(255, 255, 255, 0.1);
}
.control-btn.large:hover {
  background: rgba(255, 255, 255, 0.2);
}

/* Timeline Row */
.timeline-row {
  width: 90%;
  display: flex;
  align-items: center;
  gap: 16px;
}

.time-display {
  font-family: 'Inter', monospace;
  font-size: 14px;
  color: #FFFFFF;
  opacity: 0.8;
  min-width: 80px;
  text-align: right;
  white-space: nowrap;
}

/* Track Wrapper */
.timeline-track-wrapper {
  position: relative;
  flex: 1;
  height: 60px;
  display: flex;
  align-items: center;
}

/* The visual gray track */
.track-bg {
  position: absolute;
  width: 100%;
  height: 8px;
  background: #585863;
  border-radius: 4px;
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

/* Custom Pointer */
.custom-pointer {
  position: absolute;
  top: 0;
  height: 100%;
  width: 0;
  pointer-events: none;
  transform: translateX(-6.5px);
}

.pointer-head {
  width: 13px;
  height: 15px;
  background: #F7F7F7;
  clip-path: polygon(0 0, 100% 0, 50% 100%);
}

.pointer-line {
  width: 3px;
  height: 100%;
  background: #F7F7F7;
  margin: 0 auto;
}
</style>