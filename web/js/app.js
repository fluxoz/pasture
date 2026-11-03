// pasture: boot, views (login / dashboard / terminal), live events, menus.

import { api, Events } from './api.js';
import { Login, Enroll, logout, webauthnSupported } from './auth.js';
import { initViewport, onViewport } from './viewport.js';
import { Dashboard } from './dashboard.js';
import { TermView } from './term.js';
import { KeyBar } from './keys.js';
import { Recorder } from './dictate.js';
import { openSheet, closeSheet, item, items } from './sheet.js';
import { $, el, G, toast, storage, store, vibrate } from './util.js';

const app = $('#app');
const login = new Login();
const enroll = new Enroll();
const recorder = new Recorder();
let info = { enroll: false };
let config = null;
let dash = null;
let events = null;
let term = null;
let keybar = null;
let target = null;
let offlineTimer = 0;

// -- views ----------------------------------------------------------------

function setView(view) {
  app.dataset.view = view;
  const p = config?.providers || {};
  const onDash = view === 'dash';
  $('#act-herdr').hidden = !(onDash && p.herdr);
  $('#act-tmux').hidden = !(onDash && p.tmux && dash?.state.tmux?.default);
  $('#act-inbox').hidden = !(onDash && p.alerts);
  $('#act-new').hidden = !onDash;
  $('#act-menu').hidden = !(onDash || view === 'term');
  $('#term-status').hidden = view !== 'term';
  if (view !== 'term') $('#title').textContent = config?.appName || document.title;
  if (onDash) dash?.pumpPreviews();
}

function setConn(state) {
  $('#conn').className = `conn ${state}`;
}

// -- login and enrollment -------------------------------------------------

function loginMessage(text, error = false) {
  const m = $('#login-msg');
  m.textContent = text || ' ';
  m.classList.toggle('error', error);
}

function explain(e) {
  if (e?.name === 'NotAllowedError') return 'Cancelled';
  if (e?.name === 'InvalidStateError') return 'This passkey is already enrolled';
  if (e?.status === 0) return 'Server unreachable';
  return e?.message || String(e);
}

// The QR code from `pasture-enroll` opens /enroll#t=<token>. The fragment never
// reaches the server; take the token and drop it from the address bar.
const linkToken = (() => {
  const t = new URLSearchParams(location.hash.slice(1)).get('t') || '';
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  return t;
})();

const deviceName = () => (navigator.userAgent.match(/iPhone|iPad|Android|Macintosh|Windows|Linux/) || ['passkey'])[0];

function useLinkToken() {
  $('#enroll-token').value = linkToken;
  $('#enroll-token').hidden = true;
  if (!$('#enroll-label').value) $('#enroll-label').value = deviceName();
  $('#enroll-hint').textContent = 'Enrollment code loaded from the QR code.';
  $('#unlock').classList.remove('primary');
  $('#enroll-go').classList.add('primary');
  enroll.prefetch(linkToken).catch((e) => loginMessage(explain(e), true));
}

function showLogin(message = '') {
  closeSheet();
  setView('login');
  loginMessage(message);
  $('#enroll').hidden = !info.enroll;
  if (linkToken && !info.enroll) loginMessage('Enrollment is closed; that code was used already', true);
  if (!webauthnSupported()) {
    loginMessage('This browser has no passkey support', true);
    return;
  }
  login.prefetch().catch((e) => loginMessage(explain(e), true));
  if (linkToken && info.enroll) useLinkToken();
}

async function unlock() {
  loginMessage('');
  try {
    await login.run();
    await enterApp();
  } catch (e) {
    loginMessage(explain(e), true);
    login.prefetch().catch(() => {});
  }
}

async function doEnroll() {
  const token = $('#enroll-token').value.trim();
  const label = $('#enroll-label').value.trim() || 'passkey';
  if (token.length < 16) {
    loginMessage('Paste the enrollment token first', true);
    return;
  }
  try {
    await enroll.run(token, label);
    $('#enroll-token').value = '';
    info.enroll = false;
    // Installing from here must not start the app at /enroll, which 404s once enrollment is off.
    if (location.pathname !== '/') history.replaceState(null, '', '/');
    const installed = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
    toast(installed ? 'Passkey created' : 'Passkey created. Install the app: Share → Add to Home Screen', { ms: 8000 });
    await enterApp();
  } catch (e) {
    loginMessage(explain(e), true);
  }
}

// -- the app ----------------------------------------------------------------

async function enterApp() {
  let data;
  try {
    data = await api('/api/state');
  } catch (e) {
    if (e.status === 401) return showLogin();
    return showOffline();
  }
  clearTimeout(offlineTimer);
  login.stop();
  config = data.config;
  document.title = config.appName;
  if (config.dictation && Recorder.supported() && !keybar.hooks.dictation) {
    keybar.hooks.dictation = true;
    keybar.render();
    dash.hooks.dictateInto = toggleDictation;
  }
  dash.setConfig(config);
  dash.update(data.state);
  events.start();
  if (term) {
    setView('term');
    closeSheet();
    term.reconnect();
  } else {
    setView('dash');
  }
}

function showOffline() {
  setView('login');
  $('#enroll').hidden = true;
  loginMessage(`Can't reach ${location.host}. Retrying…`, true);
  clearTimeout(offlineTimer);
  offlineTimer = setTimeout(() => boot(false), 5000);
}

function onExpired() {
  events.stop();
  if (term) {
    // Keep the frozen terminal on screen; unlock reconnects to the same target.
    openSheet({
      title: 'Session expired',
      sub: 'Unlock to continue where you were.',
      body: [
        el('button', {
          class: 'btn primary wide',
          type: 'button',
          onclick: () =>
            login
              .run()
              .then(enterApp)
              .catch((e) => toast(explain(e), { error: true })),
          text: 'Unlock',
        }),
      ],
    });
    login.prefetch().catch(() => {});
  } else {
    showLogin('Session expired');
  }
}

function updateBadges(state) {
  const { blocked, done } = dash.counts();
  try {
    if (navigator.setAppBadge) {
      const n = blocked + done;
      if (n) navigator.setAppBadge(n).catch(() => {});
      else navigator.clearAppBadge?.().catch(() => {});
    }
  } catch {
    /* badges are optional */
  }
  const latest = state.alerts?.items?.[0]?.time || 0;
  $('#inbox-badge').hidden = !(latest > storage('inboxSeen', 0));
  $('#act-tmux').hidden = !(app.dataset.view === 'dash' && config?.providers.tmux && state.tmux?.default);
}

// -- terminal ---------------------------------------------------------------

function prefixFor(t) {
  const s = dash.state;
  if (t.k === 'agent' || t.k === 'herdr') return s.herdr?.prefix;
  if (t.k === 'tmux') return s.tmux?.prefix;
  return null;
}

async function openTerm(t) {
  closeSheet();
  if (term) term.dispose();
  target = t;
  $('#title').textContent = t.title || t.k;
  $('#term-overlay').hidden = true;
  setView('term');
  if (history.state?.term !== true) history.pushState({ term: true }, '');
  keybar.setPrefix(prefixFor(t));
  term = new TermView($('#term-host'), t, {
    onStatus: termStatus,
    onExpired,
    transform: (d) => keybar.transform(d),
  });
  await term.open();
}

function closeTerm(fromHistory = false) {
  if (dict.state !== 'idle') {
    recorder.cancel();
    endDictation();
  }
  if (term) term.dispose();
  term = null;
  target = null;
  $('#term-overlay').hidden = true;
  setView('dash');
  if (!fromHistory && history.state?.term === true) history.back();
}

function termStatus(status, msg) {
  const pill = $('#term-status');
  pill.className = `pill ${status}`;
  pill.textContent = status === 'live' ? 'live' : status === 'connecting' ? '…' : status;
  const overlay = $('#term-overlay');
  const show = status === 'exited' || (status === 'offline' && msg !== 'Session expired');
  overlay.hidden = !show;
  if (show) {
    $('#term-overlay-msg').textContent = msg || status;
    $('#term-reconnect').textContent = target?.k === 'shell' ? 'New shell' : 'Reconnect';
  }
}

function termMenu() {
  if (!term) return;
  const t = target;
  const sel = term.selection();
  const copy = (text, what) =>
    navigator.clipboard
      .writeText(text)
      .then(() => toast(`${what} copied`))
      .catch(() => toast('Clipboard not available', { error: true }));
  const found = t.k === 'agent' ? dash.findPane(t.s, t.t) : null;
  openSheet({
    title: t.title || t.k,
    sub: { agent: `herdr agent · ${t.t}`, herdr: `herdr · ${t.s || 'default'}`, tmux: 'tmux session', shell: 'login shell' }[t.k],
    body: [
      items(
        sel && item({ icon: G.copy, label: 'Copy selection', onSelect: () => copy(sel, 'Selection') }),
        item({ icon: G.copy, label: 'Copy screen', onSelect: () => copy(term.screenText(), 'Screen') }),
        found && item({ icon: G.eye, label: 'Mark seen (focuses it in herdr)', onSelect: () => api('/api/action', { method: 'POST', body: { op: 'focus', session: t.s, target: t.t } }).catch((e) => toast(e.message, { error: true })) }),
        found && item({ icon: G.send, label: 'Prompt…', onSelect: () => dash.promptSheet(t.s, found.p) }),
        item({ icon: '', label: 'Larger text', close: false, onSelect: () => term.setFontSize(term.term.options.fontSize + 1) }),
        item({ icon: '', label: 'Smaller text', close: false, onSelect: () => term.setFontSize(term.term.options.fontSize - 1) }),
        item({ icon: G.refresh, label: t.k === 'shell' ? 'New shell' : 'Reconnect', onSelect: () => term.reconnect() }),
        item({
          icon: G.term,
          label: storage('renderer', 'dom') === 'webgl' ? 'Use DOM renderer' : 'Use WebGL renderer',
          onSelect: () => {
            store('renderer', storage('renderer', 'dom') === 'webgl' ? 'dom' : 'webgl');
            openTerm(t);
          },
        }),
        config?.dictation &&
          item({
            icon: G.mic,
            label: storage('dictateEnter', '0') === '1' ? 'Dictation: stop pressing Enter' : 'Dictation: press Enter after',
            onSelect: () => store('dictateEnter', storage('dictateEnter', '0') === '1' ? '0' : '1'),
          }),
        item({ icon: G.close, label: 'Close terminal', onSelect: () => closeTerm() }),
      ),
    ],
  });
}

function dashMenu() {
  openSheet({
    title: config?.appName || 'pasture',
    sub: location.host,
    body: [
      items(
        item({ icon: G.refresh, label: 'Reload app', onSelect: () => location.reload() }),
        item({
          icon: G.signout,
          label: 'Lock',
          onSelect: () => {
            events.stop();
            logout()
              .catch(() => {})
              .then(() => showLogin('Locked'));
          },
        }),
      ),
    ],
  });
}

// -- dictation ---------------------------------------------------------------

// Tap the mic to start and again to stop, or hold it while talking and let go.
// Partial text shows while you speak; the final text goes to the sink.

const HOLD_MS = 350;
const dict = { state: 'idle', btn: null, sink: null, pressedAt: 0, stopOnRelease: false }; // idle | starting | recording | finishing

function micDown(btn, sink) {
  if (dict.state === 'recording') dict.stopOnRelease = true;
  if (dict.state !== 'idle') return;
  dict.pressedAt = Date.now();
  dict.stopOnRelease = false;
  startDictation(btn, sink);
}

function micUp() {
  // Released while still starting (permission prompt, say): keep recording, tap to stop.
  if (dict.state === 'recording' && (dict.stopOnRelease || Date.now() - dict.pressedAt >= HOLD_MS)) finishDictation();
}

function toggleDictation(btn, sink) {
  if (dict.state === 'recording') finishDictation();
  else if (dict.state === 'idle') startDictation(btn, sink);
}

function setMicTime(btn, s) {
  const time = btn?.querySelector('.time');
  if (time) time.textContent = s == null ? '' : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

async function startDictation(btn, sink) {
  Object.assign(dict, { state: 'starting', btn, sink });
  btn.classList.add('rec');
  sink.begin?.();
  try {
    await recorder.start({
      onTick: (s) => setMicTime(btn, s),
      onLimit: () => dict.state === 'recording' && finishDictation(),
      onPartial: (text) => dict.sink === sink && sink.partial?.(text),
      onLevel: (v) => {
        const level = Math.min(1, v * 2.5).toFixed(2);
        btn.style.setProperty('--level', level);
        sink.level?.(level);
      },
      onError: (e) => {
        if (dict.state !== 'recording') return;
        recorder.cancel();
        endDictation();
        toast(explain(e), { error: true });
      },
    });
    if (dict.state !== 'starting') return; // cancelled meanwhile
    dict.state = 'recording';
    vibrate(10);
  } catch (e) {
    if (dict.btn === btn) endDictation();
    if (e?.message !== 'Cancelled') toast(e?.name === 'NotAllowedError' ? 'Microphone permission denied' : explain(e), { error: true });
  }
}

async function finishDictation() {
  const { btn, sink } = dict;
  dict.state = 'finishing';
  btn.classList.remove('rec');
  btn.classList.add('busy');
  sink.busy?.();
  try {
    const text = await recorder.stop();
    if (text) sink.done(text);
    else toast('Heard nothing');
  } catch (e) {
    toast(explain(e), { error: true });
  } finally {
    if (dict.btn === btn) endDictation();
  }
}

function endDictation() {
  const { btn, sink } = dict;
  btn?.classList.remove('rec', 'busy');
  btn?.style.removeProperty('--level');
  setMicTime(btn, null);
  sink?.end?.();
  Object.assign(dict, { state: 'idle', btn: null, sink: null });
}

/** Dictating into the terminal: a live transcript over its bottom, then a paste. */
const termSink = {
  begin() {
    $('#dictation').classList.remove('busy');
    $('#dictation-text').textContent = '';
    $('#dictation').hidden = false;
  },
  partial: (text) => ($('#dictation-text').textContent = text),
  level: (v) => $('#dictation').style.setProperty('--level', v),
  busy: () => $('#dictation').classList.add('busy'),
  done(text) {
    const enter = storage('dictateEnter', '0') === '1';
    term?.paste(enter ? text : `${text} `);
    if (enter) term?.sendText('\r');
  },
  end: () => ($('#dictation').hidden = true),
};

// -- service worker --------------------------------------------------------------

function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  let reloading = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading) location.reload();
  });
  navigator.serviceWorker
    .register('/sw.js')
    .then((reg) => {
      const offer = (worker) =>
        toast('New version ready. Tap to reload.', {
          ms: 0,
          onClick: () => {
            reloading = true;
            worker.postMessage('skip-waiting');
          },
        });
      if (reg.waiting && navigator.serviceWorker.controller) offer(reg.waiting);
      reg.addEventListener('updatefound', () => {
        const worker = reg.installing;
        worker?.addEventListener('statechange', () => {
          if (worker.state === 'installed' && navigator.serviceWorker.controller) offer(worker);
        });
      });
      document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && reg.update().catch(() => {}));
    })
    .catch(() => {});
}

// -- wiring -------------------------------------------------------------------------

function wire() {
  $('#unlock').addEventListener('click', unlock);
  $('#enroll-go').addEventListener('click', doEnroll);
  $('#enroll-token').addEventListener('input', (e) => {
    const v = e.target.value.trim();
    if (v.length >= 16) enroll.prefetch(v).catch((err) => loginMessage(explain(err), true));
  });
  $('#back').addEventListener('click', () => closeTerm());
  $('#act-new').addEventListener('click', () => dash.newSheet());
  $('#act-inbox').addEventListener('click', () => {
    store('inboxSeen', Math.floor(Date.now() / 1000));
    $('#inbox-badge').hidden = true;
    dash.inboxSheet();
  });
  $('#act-herdr').addEventListener('click', () => {
    const s = dash.currentSession();
    openTerm({ k: 'herdr', s: s?.name, title: `herdr · ${s?.name || 'default'}` });
  });
  $('#act-tmux').addEventListener('click', () => {
    const name = dash.state.tmux?.default;
    if (name) openTerm({ k: 'tmux', t: name, title: name });
  });
  $('#act-menu').addEventListener('click', () => (app.dataset.view === 'term' ? termMenu() : dashMenu()));
  $('#term-reconnect').addEventListener('click', () => term?.reconnect());
  window.addEventListener('popstate', () => {
    if (term && history.state?.term !== true) closeTerm(true);
  });
  onViewport(() => term?.scheduleFit());

  keybar = new KeyBar($('#keys'), {
    send: (s) => term?.sendText(s),
    appCursor: () => term?.appCursor() ?? false,
    paste: () =>
      navigator.clipboard
        .readText()
        .then((text) => text && term?.paste(text))
        .catch(() => toast('Clipboard not available', { error: true })),
    blur: () => term?.blur(),
    dictation: false,
    onMicDown: (btn) => micDown(btn, termSink),
    onMicUp: () => micUp(),
  }, $('#keys-end'));

  dash = new Dashboard($('#dash'), {
    openTerm,
    dictateInto: null,
  });
  events = new Events({
    onState: (state) => {
      dash.update(state);
      updateBadges(state);
    },
    onAlert: (a) => {
      if (app.dataset.view === 'dash' && a.kind === 'blocked') toast(`${a.title}: needs you`);
    },
    onAuth: onExpired,
    onConn: setConn,
  });
}

async function boot(first = true) {
  if (first) {
    initViewport();
    wire();
    registerServiceWorker();
  }
  try {
    info = await api('/auth/info');
  } catch {
    return showOffline();
  }
  if (!info.loggedIn) return showLogin();
  await enterApp();
}

boot();
