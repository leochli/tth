/**
 * TTH Avatar Demo Client
 *
 * Demonstrates real-time text-to-avatar interaction with A/V sync.
 */

import { AvatarRenderer } from './avatar_renderer.js';
import { AVSyncController, createAudioContext, decodeBase64PCM } from './av_sync.js';

// Configuration
const WS_URL = `ws://${window.location.host}/v1/sessions`;
const API_URL = `/v1/sessions`;

class TTHDemoClient {
  constructor() {
    // DOM elements
    this.canvas = document.getElementById('avatar-canvas');
    this.inputEl = document.getElementById('input');
    this.responseTextEl = document.getElementById('response-text');
    this.statusEl = document.getElementById('status');
    this.driftEl = document.getElementById('drift-value');
    this.avgDriftEl = document.getElementById('avg-drift-value');
    this.latencyEl = document.getElementById('latency-value');

    // Verify required elements exist
    if (!this.canvas || !this.statusEl) {
      throw new Error('Required DOM elements not found');
    }

    // Buttons
    this.connectBtn = document.getElementById('connect');
    this.sendBtn = document.getElementById('send');
    this.interruptBtn = document.getElementById('interrupt');

    // Audio/Video
    this.audioContext = createAudioContext();
    this.renderer = new AvatarRenderer(this.canvas, this.audioContext);
    this.avSync = new AVSyncController(this.audioContext, this.renderer);

    // WebSocket
    this.ws = null;
    this.sessionId = null;
    this.isConnected = false;

    // State
    this.responseText = '';

    this._setupEventListeners();
    this._startMetricsLoop();
  }

  _setupEventListeners() {
    // Connect button
    this.connectBtn.addEventListener('click', () => this.connect());

    // Send button
    this.sendBtn.addEventListener('click', () => this.send());

    // Interrupt button
    this.interruptBtn.addEventListener('click', () => this.interrupt());

    // Enter to send
    this.inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
    });
  }

  async connect() {
    try {
      this._setStatus('Connecting...');
      this.connectBtn.disabled = true;

      // Create session
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ persona_id: 'default' }),
      });

      if (!response.ok) {
        throw new Error(`Failed to create session: ${response.status}`);
      }

      const data = await response.json();
      this.sessionId = data.session_id;

      // Connect WebSocket
      this.ws = new WebSocket(`${WS_URL}/${this.sessionId}/stream`);

      this.ws.onopen = () => {
        this.isConnected = true;
        this._setStatus(`Connected (session: ${this.sessionId.slice(0, 8)}...)`);
        this.sendBtn.disabled = false;
        this.interruptBtn.disabled = false;
        this.renderer.start();

        // Resume audio context on user interaction
        this.audioContext.resume();
      };

      this.ws.onmessage = (event) => this._handleMessage(event);

      this.ws.onclose = () => {
        this.isConnected = false;
        this._setStatus('Disconnected');
        this.sendBtn.disabled = true;
        this.interruptBtn.disabled = true;
        this.connectBtn.disabled = false;
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        this._setStatus('Connection error');
      };

    } catch (error) {
      console.error('Connection error:', error);
      this._setStatus(`Error: ${error.message}`);
      this.connectBtn.disabled = false;
    }
  }

  send() {
    const text = this.inputEl.value.trim();
    if (!text || !this.isConnected) return;

    // Clear response
    this.responseText = '';
    this.responseTextEl.textContent = '';

    // Clear A/V state for new turn
    this.avSync.reset();

    // Send message
    const message = {
      type: 'user_text',
      text: text,
      control: {
        emotion: { label: 'neutral', intensity: 0.5 },
        character: { persona_id: 'default' },
      },
    };

    this.ws.send(JSON.stringify(message));
    this.inputEl.value = '';
    this.sendBtn.disabled = true;

    // Re-enable after short delay
    setTimeout(() => {
      if (this.isConnected) this.sendBtn.disabled = false;
    }, 1000);
  }

  interrupt() {
    if (!this.isConnected) return;

    const message = { type: 'interrupt' };
    this.ws.send(JSON.stringify(message));
    this.avSync.reset();
    this._setStatus('Interrupted');
  }

  _handleMessage(event) {
    try {
      const data = JSON.parse(event.data);
      const type = data.type;

      switch (type) {
        case 'text_delta':
          this._handleTextDelta(data);
          break;

        case 'audio_chunk':
          this._handleAudioChunk(data);
          break;

        case 'video_frame':
          this._handleVideoFrame(data);
          break;

        case 'turn_complete':
          this._handleTurnComplete(data);
          break;

        case 'error':
          this._handleError(data);
          break;

        default:
          console.log('Unknown message type:', type);
      }
    } catch (error) {
      console.error('Message handling error:', error);
    }
  }

  _handleTextDelta(data) {
    this.responseText += data.token;
    this.responseTextEl.textContent = this.responseText;
  }

  _handleAudioChunk(data) {
    console.log('Audio chunk received:', data.duration_ms, 'ms, sample_rate:', data.sample_rate);
    // Decode base64 PCM
    const pcmData = decodeBase64PCM(data.data);
    this.avSync.scheduleAudioChunk(pcmData, data.sample_rate || 24000);
  }

  _handleVideoFrame(data) {
    console.log('Video frame received:', data.frame_index, data.width + 'x' + data.height);
    this.renderer.handleVideoFrame(data);
  }

  _handleTurnComplete(data) {
    this._setStatus(`Turn complete (${data.turn_id.slice(0, 8)}...)`);
  }

  _handleError(data) {
    console.error('Server error:', data);
    this._setStatus(`Error: ${data.message}`);
  }

  _setStatus(status) {
    this.statusEl.textContent = status;
  }

  _startMetricsLoop() {
    const updateMetrics = () => {
      // Update drift
      this.driftEl.textContent = this.renderer.getDrift().toFixed(1);
      this.avgDriftEl.textContent = this.renderer.getAverageDrift().toFixed(1);

      // Update latency
      this.latencyEl.textContent = this.avSync.getLatency().toFixed(2);

      requestAnimationFrame(updateMetrics);
    };
    updateMetrics();
  }
}

// Initialize - ES modules are deferred, so DOM should be ready
function initClient() {
  console.log('Demo client initializing...');
  try {
    window.client = new TTHDemoClient();
    console.log('Demo client ready');
  } catch (error) {
    console.error('Failed to initialize demo client:', error);
    const statusEl = document.getElementById('status');
    if (statusEl) {
      statusEl.textContent = `Init error: ${error.message}`;
    }
  }
}

// Check if DOM is already ready (ES modules are deferred)
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initClient);
} else {
  initClient();
}
