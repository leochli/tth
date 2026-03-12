/**
 * A/V Sync Controller for TTH
 *
 * Manages gapless audio playback with Web Audio API
 * and synchronizes video rendering with audio timeline.
 */

export class AVSyncController {
  /**
   * @param {AudioContext} audioContext - Web Audio context
   * @param {AvatarRenderer} renderer - Avatar renderer instance
   */
  constructor(audioContext, renderer) {
    this.audioContext = audioContext;
    this.renderer = renderer;
    this.audioStartTime = null;
    this.nextStartTime = 0;

    // Track scheduled sources for cleanup
    this._activeSources = [];
  }

  /**
   * Schedule PCM audio chunk for gapless playback.
   *
   * @param {ArrayBuffer} pcmData - Raw PCM audio data (16-bit mono)
   * @param {number} sampleRate - Sample rate (default: 24000 for Realtime API)
   */
  scheduleAudioChunk(pcmData, sampleRate = 24000) {
    // Create audio buffer
    const samples = pcmData.byteLength / 2;  // 16-bit = 2 bytes per sample
    const audioBuffer = this.audioContext.createBuffer(
      1,  // mono
      samples,
      sampleRate
    );

    // Convert Int16 to Float32 for Web Audio
    const channelData = audioBuffer.getChannelData(0);
    const int16View = new Int16Array(pcmData);
    for (let i = 0; i < int16View.length; i++) {
      channelData[i] = int16View[i] / 32768;
    }

    // Create source and connect
    const source = this.audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this.audioContext.destination);

    // Schedule for gapless playback
    const currentTime = this.audioContext.currentTime;
    if (this.nextStartTime < currentTime) {
      this.nextStartTime = currentTime;

      // First chunk - notify renderer
      if (this.audioStartTime === null) {
        this.audioStartTime = performance.now();
        this.renderer.setAudioStartTime(this.audioStartTime);
      }
    }

    source.start(this.nextStartTime);
    this.nextStartTime += audioBuffer.duration;

    // Track source for cleanup
    this._activeSources.push(source);
    source.onended = () => {
      const idx = this._activeSources.indexOf(source);
      if (idx >= 0) this._activeSources.splice(idx, 1);
    };

    return audioBuffer.duration;
  }

  /**
   * Schedule multiple audio chunks in sequence.
   *
   * @param {Array<ArrayBuffer>} chunks - Array of PCM audio chunks
   * @param {number} sampleRate - Sample rate
   * @returns {number} Total duration scheduled
   */
  scheduleAudioChunks(chunks, sampleRate = 24000) {
    let totalDuration = 0;
    for (const chunk of chunks) {
      totalDuration += this.scheduleAudioChunk(chunk, sampleRate);
    }
    return totalDuration;
  }

  /**
   * Get current audio position in seconds.
   * @returns {number} Current playback time
   */
  getCurrentTime() {
    return this.audioContext.currentTime;
  }

  /**
   * Get estimated latency to next scheduled audio.
   * @returns {number} Latency in seconds
   */
  getLatency() {
    return Math.max(0, this.nextStartTime - this.audioContext.currentTime);
  }

  /**
   * Reset sync state (call on interrupt or new turn).
   */
  reset() {
    // Stop all active sources
    for (const source of this._activeSources) {
      try {
        source.stop();
      } catch (e) {
        // Source may already be stopped
      }
    }
    this._activeSources = [];

    this.audioStartTime = null;
    this.nextStartTime = 0;
    this.renderer.reset();
  }

  /**
   * Pause audio playback.
   */
  pause() {
    this.audioContext.suspend();
  }

  /**
   * Resume audio playback.
   */
  resume() {
    this.audioContext.resume();
  }
}

/**
 * Create AudioContext with cross-browser support.
 * @returns {AudioContext}
 */
export function createAudioContext() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  return new AudioContextClass();
}

/**
 * Decode base64 PCM audio data.
 * @param {string} base64Data - Base64 encoded PCM data
 * @returns {ArrayBuffer} Raw PCM bytes
 */
export function decodeBase64PCM(base64Data) {
  const binaryString = atob(base64Data);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}
