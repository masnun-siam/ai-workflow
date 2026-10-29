import { useEffect, useRef, useState } from 'react';
import { formatWhen } from '../lib/format';
import { mdToHtml } from '../lib/md';
import { prdBody, renderDiagrams, toggleDiagram } from '../lib/prdRender';
import { getPrd, ShareError } from './api';
import type { PublicPrd } from './types';

const POLL_MS = 30_000;

export function SharePage() {
  const [prd, setPrd] = useState<PublicPrd | null>(null);
  const [gone, setGone] = useState(false);
  const [offline, setOffline] = useState(false);
  const prose = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      let again = true;
      try {
        const next = await getPrd(ctl.signal);
        if (ctl.signal.aborted) return;
        // Keep the old object when nothing changed so React leaves the rendered body alone.
        setPrd((cur) => (cur && cur.text === next.text && cur.title === next.title && cur.status === next.status && cur.updated_at === next.updated_at ? cur : next));
        setOffline(false);
      } catch (e) {
        if (ctl.signal.aborted) return;
        if (e instanceof ShareError && e.status === 404) { setGone(true); again = false; } else setOffline(true);
      }
      if (again) timer = setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => { ctl.abort(); clearTimeout(timer); };
  }, []);

  const text = prd?.text;
  useEffect(() => { if (text !== undefined) void renderDiagrams(prose.current); }, [text]);
  const html = text === undefined ? '' : mdToHtml(prdBody(text));
  const when = prd?.updated_at ? formatWhen(prd.updated_at) : '';

  if (gone) return <main style={{ padding: 24 }}><p>This link is no longer active</p></main>;
  return (
    <main style={{ maxWidth: 860, margin: '0 auto', padding: '24px 16px' }}>
      {offline && <p role="status">Can't reach the PRD right now, retrying</p>}
      {!prd ? (!offline && <p>Loading the PRD…</p>) : (
        <>
          <h1>{prd.title}</h1>
          <p>{prd.status && <span>{prd.status}</span>}{prd.status && when !== '' && ' · '}{when !== '' && when !== '—' && `Last updated ${when}`}</p>
          <div ref={prose} onClick={toggleDiagram} className="prose box" style={{ padding: '18px 22px' }} dangerouslySetInnerHTML={{ __html: html }} />
        </>
      )}
    </main>
  );
}
