/**
 * Avatar Renderer for TTH
 *
 * Simple canvas-based video renderer.
 * Receives JPEG frames from WebSocket and renders them to canvas.
 */

export class AvatarRenderer {
  /**
   * @param {HTMLCanvasElement} canvasElement - Canvas to render frames on
   * @param {AudioContext} audioContext - Web Audio context (for future A/V sync)
   */
  constructor(canvasElement, audioContext) {
    this.canvas = canvasElement;
    this.ctx = this.canvas.getContext('2d');
    this.audioContext = audioContext;

    // Fill canvas with initial gray
    this.ctx.fillStyle = '#2d2d44';
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

    // Frame queue
    this.frameQueue = [];
    this.maxQueueSize = 10;

    // Render state
    this.isRendering = false;
    this.audioStartTime = null;

    // Drift tracking (for metrics display)
    this.totalDrift = 0;
    this.driftSamples = [];
  }

  /**
   * Call when audio playback starts.
   * @param {number} time - Performance.now() timestamp when audio started
   */
  setAudioStartTime(time) {
    this.audioStartTime = time;
    console.log('Audio start time set:', time);
  }

  /**
   * Handle incoming video frame - render immediately.
   * @param {Object} event - VideoFrameEvent from WebSocket
   */
  handleVideoFrame(event) {
    // Drop frames if queue too full
    if (this.frameQueue.length >= this.maxQueueSize) {
      console.warn('Dropping frame - queue full');
      this.frameQueue.shift();
    }

    this.frameQueue.push(event);

    // Render immediately if not already rendering
    if (!this.isRendering) {
      this._renderNextFrame();
    }
  }

  /**
   * Start render loop.
   */
  start() {
    this.isRendering = true;
    console.log('AvatarRenderer: started');
  }

  /**
   * Stop render loop.
   */
  stop() {
    this.isRendering = false;
  }

  async _renderNextFrame() {
    if (this.frameQueue.length === 0) {
      this.isRendering = false;
      return;
    }

    this.isRendering = true;
    const frame = this.frameQueue.shift();

    try {
      // Decode base64 to bytes
      const binaryString = atob(frame.data);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      // Create blob and decode
      const blob = new Blob([bytes], { type: 'image/jpeg' });
      const bitmap = await createImageBitmap(blob);

      // Draw to canvas
      this.ctx.drawImage(bitmap, 0, 0, this.canvas.width, this.canvas.height);
      bitmap.close();

      // Update drift for metrics
      this.totalDrift = frame.drift_ms || 0;
      this.driftSamples.push(this.totalDrift);
      if (this.driftSamples.length > 100) {
        this.driftSamples.shift();
      }

      console.log('Rendered frame:', frame.frame_index);
    } catch (e) {
      console.error('Frame render error:', e);
    }

    // Continue rendering
    requestAnimationFrame(() => this._renderNextFrame());
  }

  /**
   * Get current A/V drift in milliseconds.
   * @returns {number} Drift in ms
   */
  getDrift() {
    return this.totalDrift;
  }

  /**
   * Get average drift over last 100 frames.
   * @returns {number} Average drift in ms
   */
  getAverageDrift() {
    if (this.driftSamples.length === 0) return 0;
    return this.driftSamples.reduce((a, b) => a + b, 0) / this.driftSamples.length;
  }

  /**
   * Reset renderer state.
   */
  reset() {
    this.frameQueue = [];
    this.audioStartTime = null;
    this.totalDrift = 0;
    this.driftSamples = [];

    // Clear canvas
    this.ctx.fillStyle = '#2d2d44';
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
  }
}
