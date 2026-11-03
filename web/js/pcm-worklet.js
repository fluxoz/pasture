// AudioWorklet: microphone -> 16 kHz mono 16-bit PCM in 100 ms chunks, each
// with its peak level for the meter. Downsampling averages the input samples
// that fall into each output sample (a box filter): crude, but enough for
// speech recognition. Post 'flush' to get the partial chunk at the end.

class Pcm16k extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / 16000;
    this.t = 0;
    this.sum = 0;
    this.n = 0;
    this.buf = new Int16Array(1600);
    this.len = 0;
    this.peak = 0;
    this.port.onmessage = (e) => e.data === 'flush' && this.flush(true);
  }

  flush(last = false) {
    const pcm = this.buf.slice(0, this.len);
    this.port.postMessage({ pcm: pcm.buffer, peak: this.peak, last }, [pcm.buffer]);
    this.len = 0;
    this.peak = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.sum += ch[i];
      this.n++;
      this.t += 1;
      if (this.t < this.step) continue;
      this.t -= this.step;
      let v = this.sum / this.n;
      this.sum = 0;
      this.n = 0;
      v = v < -1 ? -1 : v > 1 ? 1 : v;
      const a = v < 0 ? -v : v;
      if (a > this.peak) this.peak = a;
      this.buf[this.len++] = v * 32767;
      if (this.len === this.buf.length) this.flush();
    }
    return true;
  }
}

registerProcessor('pcm16k', Pcm16k);
