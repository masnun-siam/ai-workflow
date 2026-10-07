// Waiting-session notifications. Only ids, command and repo are ever read; question text never leaves the page.
export function isWaiting(s) {
  return !!s && s.waiting === true;
}

// Returns a function: sessions -> sessions that newly started waiting (first call only primes).
export function waitingWatcher() {
  let seen = new Map();
  let primed = false;
  return function watch(sessions) {
    const list = Array.isArray(sessions) ? sessions : [];
    const next = new Map();
    const fresh = [];
    for (const s of list) {
      if (!isWaiting(s)) continue;
      const round = s.pending_question?.id ?? '';
      next.set(s.id, round);
      if (primed && seen.get(s.id) !== round) fresh.push(s);
    }
    seen = next;
    primed = true;
    return fresh;
  };
}

export function notifyState() {
  if (typeof Notification === 'undefined' || globalThis.isSecureContext === false) return 'unavailable';
  return Notification.permission;
}

export async function requestNotify() {
  if (notifyState() === 'unavailable') return 'unavailable';
  try {
    await Notification.requestPermission();
  } catch {
    // permission prompt failed; fall through to the current state
  }
  return notifyState();
}

export function notifyWaiting(s) {
  if (notifyState() !== 'granted') return null;
  try {
    const n = new Notification('aiw: waiting on you', {
      body: `${s.command || 'A session'} · ${s.repo || 'unknown repo'}`,
      tag: 'aiw-' + s.id,
    });
    n.onclick = () => {
      globalThis.focus?.();
      location.hash = '#/answer/' + encodeURIComponent(s.id);
      n.close();
    };
    return n;
  } catch {
    return null;
  }
}

export function pageTitle(count) {
  return count > 0 ? `(${count}) aiw` : 'aiw';
}
