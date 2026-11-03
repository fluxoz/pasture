// Bottom sheets: action lists, forms, hold-to-confirm buttons.

import { $, el, glyph, vibrate } from './util.js';

let current = null;

export function closeSheet() {
  if (!current) return;
  const { wrap, onClose } = current;
  current = null;
  wrap.classList.remove('open');
  const done = () => wrap.remove();
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) done();
  else setTimeout(done, 170);
  onClose?.();
}

/**
 * openSheet({title, sub, body: Node[], onClose}) -> close()
 */
export function openSheet({ title, sub, body = [], onClose }) {
  closeSheet();
  const sheet = el(
    'div',
    { class: 'sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': title || 'menu' },
    el('div', { class: 'grab' }),
    title ? el('h2', { text: title }) : null,
    sub ? el('p', { class: 'sub', text: sub }) : null,
    ...body,
  );
  const backdrop = el('div', { class: 'sheet-backdrop', onclick: closeSheet });
  const wrap = el('div', { class: 'sheet-wrap' }, backdrop, sheet);
  $('#sheet-root').append(wrap);
  current = { wrap, onClose };
  // Start the slide on the next frame so the transition runs.
  requestAnimationFrame(() => requestAnimationFrame(() => wrap.classList.add('open')));
  return closeSheet;
}

export const sheetOpen = () => current !== null;

/**
 * A sheet row. {icon, label, danger, hold, onSelect}
 * hold: the action fires only after a 1 s press (destructive actions).
 */
export function item({ icon, label, danger = false, hold = false, onSelect, close = true }) {
  const fill = hold ? el('span', { class: 'fill' }) : null;
  const button = el(
    'button',
    { class: `item${danger ? ' danger' : ''}`, type: 'button' },
    fill,
    glyph(icon || ''),
    el('span', { text: hold ? `${label} (hold)` : label }),
  );
  const fire = () => {
    if (close) closeSheet();
    onSelect?.();
  };
  if (!hold) {
    button.addEventListener('click', fire);
    return button;
  }
  let timer = 0;
  const cancel = () => {
    clearTimeout(timer);
    button.classList.remove('holding');
  };
  button.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    button.classList.add('holding');
    timer = setTimeout(() => {
      button.classList.remove('holding');
      vibrate(20);
      fire();
    }, 1000);
  });
  for (const ev of ['pointerup', 'pointercancel', 'pointerleave']) button.addEventListener(ev, cancel);
  button.addEventListener('contextmenu', (e) => e.preventDefault());
  return button;
}

export const items = (...rows) => el('div', { class: 'items' }, ...rows.filter(Boolean));

export function field(label, input) {
  return el('label', { class: 'field' }, el('span', { text: label }), input);
}
