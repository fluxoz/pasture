// Dictation, transcribed on the server by whisper.cpp.
//
// Streaming (AudioWorklet): 16 kHz PCM goes to /ws/dictate while you talk,
// partial text comes back as you speak and the final text right after you
// stop. Browsers without AudioWorklet record with MediaRecorder and upload
// the clip to /api/dictate. Either way the microphone is released as soon as
// recording stops, so the iOS mic indicator goes away.

import { api } from './api.js';

const MAX_MS = 60_000;
const FINAL_TIMEOUT_MS = 20_000;

export class Recorder {
  constructor() {
    this.mode = null; // 'stream' | 'upload' while recording
    this.stream = null;
    this.ctx = null;
    this.node = null;
    this.ws = null;
    this.queue = [];
    this.final = null;
    this.rec = null;
    this.chunks = [];
    this.timers = [];
  }

  get active() {
    return this.mode !== null;
  }

  static supported() {
    return !!(navigator.mediaDevices?.getUserMedia && (window.AudioWorkletNode || window.MediaRecorder));
  }

  /**
   * Start recording. Call it straight from the tap: iOS starts audio only inside a gesture.
   * hooks: onTick(seconds), onLimit(), onPartial(text), onLevel(0..1), onReady(),
   * onError(err) when the transcriber fails mid-recording.
   */
  async start(hooks = {}) {
    if (this.active) return;
    if (window.AudioWorkletNode) await this.startStream(hooks);
    else await this.startUpload();
    const started = Date.now();
    this.timers = [
      setInterval(() => hooks.onTick?.(Math.floor((Date.now() - started) / 1000)), 250),
      setTimeout(() => hooks.onLimit?.(), MAX_MS),
    ];
    hooks.onTick?.(0);
  }

  async startStream({ onPartial, onLevel, onReady, onLimit, onError }) {
    this.mode = 'stream';
    this.failed = null;
    const ctx = new AudioContext(); // created in the gesture, before any await
    this.ctx = ctx;
    const resumed = ctx.resume();
    let settle;
    this.final = new Promise((resolve, reject) => (settle = { resolve, reject }));
    this.final.catch(() => {});
    this.queue = [];
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/dictate`);
    ws.binaryType = 'arraybuffer';
    this.ws = ws;
    ws.onopen = () => {
      for (const m of this.queue) ws.send(m);
      this.queue = null;
    };
    const fail = (err) => {
      settle.reject(err);
      if (this.ws !== ws || this.mode !== 'stream' || this.failed) return;
      this.failed = err;
      if (this.node) onError?.(err); // still starting: start() throws it instead
    };
    ws.onmessage = (e) => {
      let m;
      try {
        m = JSON.parse(e.data);
      } catch {
        return;
      }
      if (m.t === 'ready') onReady?.();
      else if (m.t === 'partial') onPartial?.(m.text);
      else if (m.t === 'final') {
        settle.resolve(m.text || '');
        if (m.limit) onLimit?.();
      } else if (m.t === 'error') fail(new Error(m.message || 'Dictation failed'));
    };
    ws.onclose = () => fail(new Error('Dictation connection lost'));
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      await ctx.audioWorklet.addModule('/js/pcm-worklet.js');
      await resumed;
      if (this.failed) throw this.failed;
      if (this.mode !== 'stream') throw new Error('Cancelled');
    } catch (e) {
      this.cancel();
      throw e;
    }
    const node = new AudioWorkletNode(ctx, 'pcm16k');
    this.node = node;
    node.port.onmessage = (e) => {
      const { pcm, peak, last } = e.data;
      onLevel?.(peak);
      if (pcm.byteLength) this.send(pcm);
      if (last) this.flushed?.();
    };
    // The worklet only has to run, not be heard: route it into a muted gain.
    const mute = ctx.createGain();
    mute.gain.value = 0;
    ctx.createMediaStreamSource(this.stream).connect(node).connect(mute).connect(ctx.destination);
  }

  send(data) {
    if (this.queue) this.queue.push(data);
    else if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(data);
  }

  async startUpload() {
    this.mode = 'upload';
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
    } catch (e) {
      this.mode = null;
      throw e;
    }
    const types = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
    const mimeType = types.find((t) => MediaRecorder.isTypeSupported?.(t));
    this.rec = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
    this.chunks = [];
    this.rec.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.rec.start(1000);
  }

  /** Stop and transcribe. Resolves to the text. */
  async stop() {
    const mode = this.mode;
    this.clearTimers();
    if (mode === 'stream') {
      // Collect the worklet's last partial chunk before the mic goes away.
      await new Promise((resolve) => {
        this.flushed = resolve;
        this.node ? this.node.port.postMessage('flush') : resolve();
        setTimeout(resolve, 250);
      });
      this.flushed = null;
      this.releaseAudio();
      this.send(JSON.stringify({ t: 'stop' }));
      const final = this.final;
      const ws = this.ws;
      this.mode = null;
      try {
        return await Promise.race([
          final,
          new Promise((_, reject) => setTimeout(() => reject(new Error('Transcription timed out')), FINAL_TIMEOUT_MS)),
        ]);
      } finally {
        ws?.close();
        this.ws = null;
      }
    }
    if (mode === 'upload') {
      const rec = this.rec;
      const stopped = new Promise((r) => rec.addEventListener('stop', r, { once: true }));
      if (rec.state !== 'inactive') rec.stop();
      await stopped;
      this.releaseAudio();
      this.mode = null;
      const blob = new Blob(this.chunks, { type: (rec.mimeType || 'audio/mp4').split(';')[0] });
      this.chunks = [];
      if (blob.size < 512) return '';
      const res = await api('/api/dictate', { method: 'POST', body: blob });
      return res.text || '';
    }
    return '';
  }

  cancel() {
    this.clearTimers();
    if (this.ws) {
      this.send(JSON.stringify({ t: 'cancel' }));
      this.ws.close();
      this.ws = null;
    }
    if (this.rec && this.rec.state !== 'inactive') this.rec.stop();
    this.releaseAudio();
    this.chunks = [];
    this.mode = null;
  }

  clearTimers() {
    clearInterval(this.timers[0]);
    clearTimeout(this.timers[1]);
    this.timers = [];
  }

  releaseAudio() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    if (this.node) this.node.port.onmessage = null;
    this.node = null;
    this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.rec = null;
  }
}
