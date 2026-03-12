/**
 * TTH Avatar Demo Client
 *
 * Supports two modes:
 * 1. Server-side frames: Video frames sent via WebSocket
 * 2. D-ID WebRTC: Browser connects directly to D-ID via WebRTC
 */

import { AvatarRenderer } from './avatar_renderer.js';
import { AVSyncController, createAudioContext, decodeBase64PCM } from './av_sync.js';
import { DIDWebRTCClient } from './did_webrtc.js';

// Configuration
const WS_URL = `ws://${window.location.host}/v1/sessions`;
const API_URL = `/v1/sessions`;

class TTHDemoClient {
  constructor() {
    console.log('TTHDemoClient constructor starting...');
    // DOM elements
    this.canvas = document.getElementById('avatar-canvas');
    this.video = document.getElementById('avatar-video');
    this.inputEl = document.getElementById('input');
    this.responseTextEl = document.getElementById('response-text');
    this.statusEl = document.getElementById('status');
    this.driftEl = document.getElementById('drift-value');
    this.avgDriftEl = document.getElementById('avg-drift-value');
    this.latencyEl = document.getElementById('latency-value');

    console.log('DOM elements:', {
      canvas: !!this.canvas,
      video: !!this.video,
      statusEl: !!this.statusEl
    });

    // Verify required elements exist
    if (!this.canvas || !this.video || !this.statusEl) {
      throw new Error('Required DOM elements not found');
    }

    // Buttons
    this.connectBtn = document.getElementById('connect');
    this.connectDIDBtn = document.getElementById('connect-did');
    this.sendBtn = document.getElementById('send');
    this.interruptBtn = document.getElementById('interrupt');

    console.log('Buttons:', {
      connectBtn: !!this.connectBtn,
      connectDIDBtn: !!this.connectDIDBtn,
      sendBtn: !!this.sendBtn,
      interruptBtn: !!this.interruptBtn
    });

    // Audio/Video (for server-side mode)
    this.audioContext = createAudioContext();
    this.renderer = new AvatarRenderer(this.canvas, this.audioContext);
    this.avSync = new AVSyncController(this.audioContext, this.renderer);

    // D-ID WebRTC client
    this.didClient = null;

    // WebSocket
    this.ws = null;
    this.sessionId = null;
    this.isConnected = false;
    this.mode = null; // 'server' or 'did'

    // State
    this.responseText = '';

    this._setupEventListeners();
    this._startMetricsLoop();
  }

  _setupEventListeners() {
    // Connect button (server-side frames)
    this.connectBtn.addEventListener('click', () => this.connectServer());

    // Connect D-ID button (WebRTC mode)
    this.connectDIDBtn.addEventListener('click', () => this.connectDID());

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

  async connectServer() {
    try {
      this._setStatus('Connecting (server mode)...');
      this.connectBtn.disabled = true;
      this.connectDIDBtn.disabled = true;

      // Show canvas, hide video
      this.canvas.style.display = 'block';
      this.video.style.display = 'none';

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
        this.mode = 'server';
        this._setStatus(`Connected (server mode: ${this.sessionId.slice(0, 8)}...)`);
        this.sendBtn.disabled = false;
        this.interruptBtn.disabled = false;
        this.renderer.start();

        // Resume audio context on user interaction
        this.audioContext.resume();
      };

      this.ws.onmessage = (event) => this._handleMessage(event);

      this.ws.onclose = () => {
        this._handleDisconnect();
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        this._setStatus('Connection error');
      };

    } catch (error) {
      console.error('Connection error:', error);
      this._setStatus(`Error: ${error.message}`);
      this.connectBtn.disabled = false;
      this.connectDIDBtn.disabled = false;
    }
  }

  async connectDID() {
    console.log('connectDID called');
    try {
      this._setStatus('Connecting (D-ID WebRTC)...');
      this.connectBtn.disabled = true;
      this.connectDIDBtn.disabled = true;

      // Show video, hide canvas
      this.video.style.display = 'block';
      this.canvas.style.display = 'none';

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

      // Create D-ID WebRTC client
      this.didClient = new DIDWebRTCClient(this.video, {
        apiBase: '/v1/did/sessions',
        onStatusChange: (status) => {
          if (status === 'connected') {
            this.isConnected = true;
            this.mode = 'did';
            this._setStatus(`Connected (D-ID: ${this.sessionId.slice(0, 8)}...)`);
            this.sendBtn.disabled = false;
            this.interruptBtn.disabled = false;
          } else if (status === 'disconnected' || status === 'error') {
            this._handleDisconnect();
          }
        },
        onError: (error) => {
          console.error('D-ID error:', error);
          this._setStatus(`D-ID Error: ${error.message}`);
        },
      });

      // Connect to D-ID
      const success = await this.didClient.connect(this.sessionId);
      if (!success) {
        throw new Error('Failed to connect to D-ID');
      }

    } catch (error) {
      console.error('D-ID connection error:', error);
      this._setStatus(`Error: ${error.message}`);
      this.connectBtn.disabled = false;
      this.connectDIDBtn.disabled = false;
    }
  }

  _handleDisconnect() {
    this.isConnected = false;
    this.mode = null;
    this._setStatus('Disconnected');
    this.sendBtn.disabled = true;
    this.interruptBtn.disabled = true;
    this.connectBtn.disabled = false;
    this.connectDIDBtn.disabled = false;
  }

  send() {
    const text = this.inputEl.value.trim();
    if (!text || !this.isConnected) return;

    // Clear response
    this.responseText = '';
    this.responseTextEl.textContent = '';

    if (this.mode === 'server') {
      // Server mode: send via WebSocket
      this.avSync.reset();

      const message = {
        type: 'user_text',
        text: text,
        control: {
          emotion: { label: 'neutral', intensity: 0.5 },
          character: { persona_id: 'default' },
        },
      };

      this.ws.send(JSON.stringify(message));
    } else if (this.mode === 'did') {
      // D-ID mode: send text directly to D-ID
      this.didClient.speak(text);
    }

    this.inputEl.value = '';
    this.sendBtn.disabled = true;

    // Re-enable after short delay
    setTimeout(() => {
      if (this.isConnected) this.sendBtn.disabled = false;
    }, 1000);
  }

  interrupt() {
    if (!this.isConnected) return;

    if (this.mode === 'server') {
      const message = { type: 'interrupt' };
      this.ws.send(JSON.stringify(message));
      this.avSync.reset();
    }
    // D-ID mode doesn't support interrupt via chat API

    this._setStatus('Interrupted');
  }

  _handleMessage(event) {
    // Only handle messages in server mode
    if (this.mode !== 'server') return;

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
      // Update drift (only for server mode)
      if (this.mode === 'server') {
        this.driftEl.textContent = this.renderer.getDrift().toFixed(1);
        this.avgDriftEl.textContent = this.renderer.getAverageDrift().toFixed(1);
        this.latencyEl.textContent = this.avSync.getLatency().toFixed(2);
      } else {
        this.driftEl.textContent = '--';
        this.avgDriftEl.textContent = '--';
        this.latencyEl.textContent = '--';
      }

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
    console.log('Connect button:', window.client.connectBtn);
    console.log('Connect D-ID button:', window.client.connectDIDBtn);
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
  console.log('DOM already ready, initializing...');
  initClient();
}
