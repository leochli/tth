/**
 * D-ID WebRTC Client
 *
 * Handles WebRTC connection to D-ID streaming service.
 * Server creates the session, browser connects directly to D-ID for video.
 */

export class DIDWebRTCClient {
  /**
   * @param {HTMLVideoElement} videoElement - Video element for avatar playback
   * @param {object} options - Configuration options
   */
  constructor(videoElement, options = {}) {
    this.videoElement = videoElement;
    this.apiBase = options.apiBase || '/v1/did/sessions';
    this.sessionId = null;
    this.pc = null; // RTCPeerConnection
    this.isConnected = false;
    this.onStatusChange = options.onStatusChange || (() => {});
    this.onError = options.onError || console.error;
  }

  /**
   * Connect to D-ID streaming session.
   * @param {string} sessionId - Our internal session ID
   * @returns {Promise<boolean>} Success status
   */
  async connect(sessionId) {
    this.sessionId = sessionId;
    this._setStatus('connecting');

    try {
      // 1. Get connection info from server (creates D-ID agent/stream)
      const response = await fetch(`${this.apiBase}/${sessionId}/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        throw new Error(`Failed to create D-ID connection: ${response.status}`);
      }

      const connInfo = await response.json();

      if (connInfo.error) {
        throw new Error(connInfo.error);
      }

      console.log('D-ID connection info:', connInfo);

      // 2. Create RTCPeerConnection
      console.log('Creating RTCPeerConnection with ICE servers:', connInfo.ice_servers);
      this.pc = new RTCPeerConnection({
        iceServers: connInfo.ice_servers || [{ urls: 'stun:stun.l.google.com:19302' }],
      });

      // 3. Handle incoming media tracks (video + audio)
      this.pc.ontrack = (event) => {
        console.log('D-ID: Received media track', event.track.kind);
        if (event.streams && event.streams[0]) {
          console.log('D-ID: Setting video srcObject');
          this.videoElement.srcObject = event.streams[0];
          this.videoElement.muted = false;
          this.videoElement.play().catch(e => console.warn('Video autoplay failed:', e));
        }
      };

      // 4. Handle ICE candidates - send to server
      this.pc.onicecandidate = async (event) => {
        if (event.candidate) {
          console.log('D-ID: Sending ICE candidate');
          await this._sendICE(event.candidate);
        }
      };

      // 5. Handle connection state changes
      this.pc.onconnectionstatechange = () => {
        console.log('D-ID connection state:', this.pc.connectionState);
        switch (this.pc.connectionState) {
          case 'connected':
            this.isConnected = true;
            this._setStatus('connected');
            break;
          case 'disconnected':
          case 'failed':
          case 'closed':
            this.isConnected = false;
            this._setStatus('disconnected');
            break;
        }
      };

      // 6. Set remote description (SDP offer from D-ID)
      console.log('Setting remote description, offer exists:', !!connInfo.offer);
      if (connInfo.offer) {
        await this.pc.setRemoteDescription(
          new RTCSessionDescription(connInfo.offer)
        );
        console.log('Remote description set');

        // 7. Create and send answer
        const answer = await this.pc.createAnswer();
        await this.pc.setLocalDescription(answer);
        console.log('Local description (answer) created');

        await this._sendSDP(answer);
        console.log('SDP answer sent');
      }

      return true;

    } catch (error) {
      console.error('D-ID connection error:', error);
      this.onError(error);
      this._setStatus('error');
      return false;
    }
  }

  /**
   * Send SDP answer to D-ID via server.
   * @param {RTCSessionDescription} answer
   */
  async _sendSDP(answer) {
    const response = await fetch(`${this.apiBase}/${this.sessionId}/sdp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sdp: answer.sdp,
        type: answer.type,
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to send SDP: ${response.status}`);
    }
  }

  /**
   * Send ICE candidate to D-ID via server.
   * @param {RTCIceCandidate} candidate
   */
  async _sendICE(candidate) {
    console.log('D-ID: Sending ICE candidate:', candidate);
    try {
      const response = await fetch(`${this.apiBase}/${this.sessionId}/ice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(candidate.toJSON()),
      });

      if (!response.ok) {
        console.warn('D-ID: Failed to send ICE candidate:', response.status);
        return;
      }
      console.log('D-ID: ICE response:', response.status);
    } catch (error) {
      console.warn('D-ID: Failed to send ICE candidate:', error);
    }
  }

  /**
   * Send text to D-ID agent for speaking.
   * @param {string} text - Text for the agent to speak
   * @returns {Promise<boolean>} Success status
   */
  async speak(text) {
    if (!this.sessionId || !this.isConnected) {
      console.error('D-ID: Not connected');
      return false;
    }

    try {
      const response = await fetch(`${this.apiBase}/${this.sessionId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });

      const result = await response.json();
      if (!result.success) {
        console.error('D-ID: Failed to send text:', result.error);
        return false;
      }
      return true;
    } catch (error) {
      console.error('D-ID: Failed to send text:', error);
      return false;
    }
  }

  /**
   * Disconnect from D-ID session.
   */
  async disconnect() {
    if (this.pc) {
      this.pc.close();
      this.pc = null;
    }

    if (this.sessionId) {
      try {
        await fetch(`${this.apiBase}/${this.sessionId}`, {
          method: 'DELETE',
        });
      } catch (error) {
        console.warn('D-ID: Failed to close session:', error);
      }
    }

    this.isConnected = false;
    this.sessionId = null;
    this._setStatus('disconnected');
  }

  /**
   * Update connection status.
   * @param {string} status
   */
  _setStatus(status) {
    this.onStatusChange(status);
  }
}

/**
 * Create a D-ID WebRTC client.
 * @param {HTMLVideoElement} videoElement
 * @param {object} options
 * @returns {DIDWebRTCClient}
 */
export function createDIDClient(videoElement, options = {}) {
  return new DIDWebRTCClient(videoElement, options);
}
