// Pin #app to the *visual* viewport so the iOS keyboard never pushes,
// bounces or scrolls the page: height = visible height, translateY = how far
// iOS scrolled the visual viewport. One rAF per change, CSS vars only.

let listeners = [];

export function onViewport(fn) {
  listeners.push(fn);
}

export function initViewport() {
  const vv = window.visualViewport;
  const root = document.documentElement;
  let raf = 0;
  let last = '';

  const apply = () => {
    raf = 0;
    const h = vv ? vv.height : window.innerHeight;
    const top = vv ? Math.max(0, vv.offsetTop) : 0;
    const key = `${h}:${top}`;
    if (key === last) return;
    last = key;
    root.style.setProperty('--vvh', `${Math.round(h)}px`);
    root.style.setProperty('--vvt', `${Math.round(top)}px`);
    // A visual viewport much shorter than the layout viewport means the keyboard is up.
    root.classList.toggle('kb-open', window.innerHeight - h > 120);
    for (const fn of listeners) fn();
  };
  const schedule = () => {
    if (!raf) raf = requestAnimationFrame(apply);
  };

  vv?.addEventListener('resize', schedule);
  vv?.addEventListener('scroll', schedule);
  window.addEventListener('resize', schedule);
  window.addEventListener('orientationchange', () => setTimeout(schedule, 50));
  // iOS scrolls the focused field into view; the fixed layout already shows it.
  document.addEventListener('focusin', () => {
    window.scrollTo(0, 0);
    schedule();
  });
  document.addEventListener('focusout', () => setTimeout(schedule, 50));
  // Nothing on the page should scroll the document itself.
  document.addEventListener('scroll', () => window.scrollTo(0, 0), { passive: true });
  apply();
}
