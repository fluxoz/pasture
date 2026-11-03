// Tap-to-start / tap-to-stop recording, transcribed on the server by
// whisper.cpp (/api/dictate). The microphone is released as soon as
// recording stops, so the iOS mic indicator goes away.

import { api } from './api.js';

const MAX_MS = 60_000;

export class Recorder {
  constructor() {
    this.rec = null;
    this.stream = null;
    this.chunks = [];
    this.started = 0;
    this.tick = 0;
    this.limit = 0;
  }

  get active() {
    return this.rec !== null;
  }

  static supported() {
    return !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
  }

  /** Start recording. onTick(seconds) updates the timer; onLimit() fires at the cap. */
  async start({ onTick, onLimit } = {}) {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
    const types = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
    const mimeType = types.find((t) => MediaRecorder.isTypeSupported?.(t));
    this.rec = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
    this.chunks = [];
    this.rec.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.rec.start(1000);
    this.started = Date.now();
    this.tick = setInterval(() => onTick?.(Math.floor((Date.now() - this.started) / 1000)), 250);
    this.limit = setTimeout(() => onLimit?.(), MAX_MS);
    onTick?.(0);
  }

  /** Stop and transcribe. Resolves to the text. */
  async stop() {
    const rec = this.rec;
    if (!rec) return '';
    clearInterval(this.tick);
    clearTimeout(this.limit);
    const stopped = new Promise((r) => rec.addEventListener('stop', r, { once: true }));
    if (rec.state !== 'inactive') rec.stop();
    await stopped;
    this.release();
    const blob = new Blob(this.chunks, { type: (rec.mimeType || 'audio/mp4').split(';')[0] });
    this.chunks = [];
    if (blob.size < 512) return '';
    const res = await api('/api/dictate', { method: 'POST', body: blob });
    return res.text || '';
  }

  cancel() {
    clearInterval(this.tick);
    clearTimeout(this.limit);
    if (this.rec && this.rec.state !== 'inactive') this.rec.stop();
    this.release();
    this.chunks = [];
  }

  release() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.rec = null;
  }
}
