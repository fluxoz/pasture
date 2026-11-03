// The mobile key bar: Esc, Tab, sticky Ctrl/Alt, arrows with auto-repeat,
// a few symbols, the multiplexer prefix, PgUp/PgDn, paste, mic, hide keyboard.
//
// Buttons act on pointerdown and preventDefault() it, so xterm's hidden
// textarea keeps focus and the iOS keyboard stays up.

import { el, glyph, G, vibrate } from './util.js';

const ARROWS = { left: 'D', down: 'B', up: 'A', right: 'C' };

export class KeyBar {
  /**
   * @param {HTMLElement} host
   * @param {{send:(s:string)=>void, appCursor:()=>boolean, paste:()=>void,
   *          blur:()=>void, dictation:boolean, onMic:(btn:HTMLElement)=>void}} hooks
   */
  constructor(host, hooks) {
    this.host = host;
    this.hooks = hooks;
    this.ctrl = 'off'; // off | once | lock
    this.alt = 'off';
    this.prefix = null;
    this.render();
  }

  setPrefix(bytes) {
    this.prefix = bytes || null;
    this.prefixBtn.hidden = !this.prefix;
  }

  /** Apply sticky modifiers to text typed on the soft keyboard. */
  transform(data) {
    if (this.ctrl === 'off' && this.alt === 'off') return data;
    let out = data;
    if (this.ctrl !== 'off' && data.length === 1) out = ctrlChar(data);
    if (this.alt !== 'off') out = '\x1b' + out;
    this.release();
    return out;
  }

  release() {
    if (this.ctrl === 'once') this.ctrl = 'off';
    if (this.alt === 'once') this.alt = 'off';
    this.paintMods();
  }

  paintMods() {
    for (const [btn, state] of [
      [this.ctrlBtn, this.ctrl],
      [this.altBtn, this.alt],
    ]) {
      btn.classList.toggle('on', state === 'once');
      btn.classList.toggle('lock', state === 'lock');
    }
  }

  toggleMod(which) {
    const now = Date.now();
    const key = `${which}Tap`;
    const state = this[which];
    if (state === 'once' && now - (this[key] || 0) < 350) this[which] = 'lock';
    else this[which] = state === 'off' ? 'once' : 'off';
    this[key] = now;
    this.paintMods();
  }

  sendKey(seq) {
    const ctrl = this.ctrl !== 'off';
    const alt = this.alt !== 'off';
    let out = seq;
    if (ctrl && seq.length === 1) out = ctrlChar(seq);
    if (alt) out = '\x1b' + out;
    this.release();
    this.hooks.send(out);
  }

  arrow(dir) {
    const ctrl = this.ctrl !== 'off';
    const alt = this.alt !== 'off';
    const mod = 1 + (alt ? 2 : 0) + (ctrl ? 4 : 0);
    let seq;
    if (mod > 1) seq = `\x1b[1;${mod}${ARROWS[dir]}`;
    else seq = (this.hooks.appCursor() ? '\x1bO' : '\x1b[') + ARROWS[dir];
    this.release();
    this.hooks.send(seq);
  }

  button(label, { cls = 'key', aria, down, click, repeat = false }) {
    const btn = el('button', { class: cls, type: 'button', 'aria-label': aria || undefined }, label);
    let delay = 0;
    let rate = 0;
    const stop = () => {
      clearTimeout(delay);
      clearInterval(rate);
      btn.classList.remove('down');
    };
    btn.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      if (!down) return;
      btn.classList.add('down');
      vibrate(6);
      down();
      if (repeat) delay = setTimeout(() => (rate = setInterval(down, 60)), 400);
    });
    for (const ev of ['pointerup', 'pointercancel', 'pointerleave']) btn.addEventListener(ev, stop);
    if (click) btn.addEventListener('click', click);
    btn.addEventListener('contextmenu', (e) => e.preventDefault());
    return btn;
  }

  render() {
    const k = (label, seq, opts = {}) => this.button(label, { down: () => this.sendKey(seq), ...opts });
    const arrow = (label, dir) => this.button(label, { down: () => this.arrow(dir), repeat: true, aria: dir });
    this.ctrlBtn = this.button('ctrl', { cls: 'key mod', down: () => this.toggleMod('ctrl') });
    this.altBtn = this.button('alt', { cls: 'key mod', down: () => this.toggleMod('alt') });
    this.prefixBtn = this.button('pfx', {
      cls: 'key mod',
      aria: 'multiplexer prefix',
      down: () => this.prefix && this.hooks.send(this.prefix),
    });
    this.prefixBtn.hidden = true;
    this.micBtn = null;
    if (this.hooks.dictation) {
      this.micBtn = this.button('', { cls: 'key', aria: 'dictate', click: () => this.hooks.onMic(this.micBtn) });
      this.micBtn.append(glyph(G.mic), el('span', { class: 'time' }));
    }
    const row = [
      k('esc', '\x1b', { cls: 'key mod' }),
      k('tab', '\t', { cls: 'key mod' }),
      this.ctrlBtn,
      this.altBtn,
      arrow('←', 'left'),
      arrow('↓', 'down'),
      arrow('↑', 'up'),
      arrow('→', 'right'),
      this.prefixBtn,
      this.micBtn,
      k('|', '|'),
      k('~', '~'),
      k('/', '/'),
      k('-', '-'),
      k('_', '_'),
      k('⇞', '\x1b[5~', { repeat: true, aria: 'page up' }),
      k('⇟', '\x1b[6~', { repeat: true, aria: 'page down' }),
      k('^C', '\x03', { cls: 'key mod' }),
      this.button(glyph(G.paste), { aria: 'paste', click: () => this.hooks.paste() }),
      this.button(glyph(G.keyboard), { aria: 'hide keyboard', click: () => this.hooks.blur() }),
    ].filter(Boolean);
    this.host.replaceChildren(...row);
  }
}

function ctrlChar(ch) {
  const c = ch.toLowerCase();
  if (c >= 'a' && c <= 'z') return String.fromCharCode(c.charCodeAt(0) - 96);
  const table = { '[': '\x1b', '\\': '\x1c', ']': '\x1d', '^': '\x1e', _: '\x1f', '/': '\x1f', ' ': '\x00', '@': '\x00', '?': '\x7f' };
  return table[c] ?? ch;
}
