import { useCallback, useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Icon } from '../components';

const read = (el: HTMLElement | null) => ({
  overflow: !!el && el.scrollHeight > el.clientHeight,
  atTop: !el || el.scrollTop <= 0,
  atBottom: !el || el.scrollTop + el.clientHeight >= el.scrollHeight - 1,
});

/** Floating jump-to-top / jump-to-bottom for the page scroller (#main-content); renders nothing when the page fits. */
export function ScrollJump() {
  const { pathname } = useLocation();
  const [s, setS] = useState(() => read(null));
  const update = useCallback(() => setS(read(document.getElementById('main-content'))), []);
  useEffect(() => {
    const el = document.getElementById('main-content');
    update();
    if (!el) return;
    el.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    const ro = new ResizeObserver(update);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    return () => {
      el.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      ro.disconnect();
    };
  }, [pathname, update]);
  if (!s.overflow) return null;
  const jump = (end: boolean) => {
    const el = document.getElementById('main-content');
    el?.scrollTo({ top: end ? el.scrollHeight : 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  };
  return (
    <div className="scroll-jump">
      {s.atTop ? null : <button type="button" className="btn icon" aria-label="Jump to top" onClick={() => jump(false)}><Icon n="up" /></button>}
      {s.atBottom ? null : <button type="button" className="btn icon" aria-label="Jump to bottom" onClick={() => jump(true)}><Icon n="down" /></button>}
    </div>
  );
}
