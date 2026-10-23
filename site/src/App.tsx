import { useEffect, useRef, useState } from 'react';
import { REPO, run, stages, tour } from './content';

const base = import.meta.env.BASE_URL;
const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

type MediaProps = { src: string; poster?: string; kind: 'video' | 'image'; alt?: string; eager?: boolean };

function Media({ src, poster, kind, alt = '', eager }: MediaProps) {
  if (kind === 'image') return <img src={base + src} alt={alt} loading={eager ? 'eager' : 'lazy'} decoding="async" />;
  return (
    <video
      src={base + src}
      poster={poster && base + poster}
      aria-label={alt}
      muted
      loop
      playsInline
      autoPlay={!reduced}
      controls={reduced}
      preload={eager ? 'auto' : 'metadata'}
    />
  );
}

function Window({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <figure className="window">
      <div className="window-bar" aria-hidden="true">
        <i /><i /><i />
        <span>{title}</span>
      </div>
      {children}
    </figure>
  );
}

function StarLink({ big }: { big?: boolean }) {
  return (
    <a className={big ? 'btn primary big' : 'btn primary'} href={REPO}>
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <path fill="currentColor" d="M8 .25a.75.75 0 0 1 .67.42l1.88 3.8 4.2.61a.75.75 0 0 1 .41 1.28l-3.04 2.96.72 4.18a.75.75 0 0 1-1.09.79L8 12.31 4.25 14.3a.75.75 0 0 1-1.09-.79l.72-4.18L.84 6.36a.75.75 0 0 1 .41-1.28l4.2-.61L7.33.67A.75.75 0 0 1 8 .25Z" />
      </svg>
      Star on GitHub
    </a>
  );
}

function Hero() {
  return (
    <header className="hero">
      <nav className="top">
        <a className="mark" href="#top" aria-label="ai-workflow home">
          <span className="logo" aria-hidden="true" />ai-workflow
        </a>
        <a className="ghost" href={REPO}>GitHub</a>
      </nav>
      <div className="hero-copy" id="top">
        <h1>Type an idea.<br />Get back a reviewed pull request.</h1>
        <p className="lede">
          A Claude Code plugin that runs a real team process: a PRD that reviewers sign off, small issues, code
          written and checked in its own worktree, and a PR reviewed before you see it. One local UI shows where
          everything stands and asks you only what needs a person.
        </p>
        <div className="ctas">
          <StarLink big />
          <a className="btn" href="#run">Watch a real run</a>
        </div>
      </div>
      <div className="hero-shot">
        <Window title="aiw ui · masnun-siam/todoman">
          <Media kind="video" src="media/hero.mp4" poster="media/hero.webp" alt="The aiw UI: starting a feature, answering Claude, watching the board fill in" eager />
        </Window>
      </div>
    </header>
  );
}

/** The signature: the UI's own stage stepper as the page's spine. Scroll position picks the stage. */
function Pipeline() {
  const [active, setActive] = useState(0);
  const refs = useRef<(HTMLElement | null)[]>([]);

  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.i));
      },
      { rootMargin: '-45% 0px -50% 0px' },
    );
    refs.current.forEach((el) => el && io.observe(el));
    return () => io.disconnect();
  }, []);

  return (
    <section className="pipeline" aria-labelledby="pipeline-h">
      <div className="section-head">
        <h2 id="pipeline-h">Seven stages. Three decisions are yours.</h2>
        <p>
          Machine steps run on their own. The amber gates are where a person decides. Every screen below is from the
          same real run on a personal project.
        </p>
      </div>
      <div className="pipe">
        <ol className="rail" style={{ ['--p' as string]: active / (stages.length - 1) }}>
          {stages.map((s, i) => (
            <li key={s.id} className={i === active ? 'on' : i < active ? 'done' : ''}>
              <a href={`#stage-${s.id}`}>
                <span className="dot" aria-hidden="true" />
                <span className="rail-name">{s.name}</span>
                {s.gate && <span className="gate">{s.gate}</span>}
              </a>
            </li>
          ))}
        </ol>
        <div className="stages">
          {stages.map((s, i) => (
            <article
              key={s.id}
              id={`stage-${s.id}`}
              data-i={i}
              ref={(el) => { refs.current[i] = el; }}
              className={i === active ? 'stage on' : 'stage'}
            >
              <div className="stage-text">
                <h3>
                  <span className="num">{i + 1}</span>
                  {s.name}
                </h3>
                <code>{s.cmd}</code>
                <p>{s.body}</p>
                {s.gate && <p className="gate-note">{s.gate}</p>}
              </div>
              <Window title={s.cmd}>
                <Media {...s.media} />
              </Window>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function Tour() {
  const [tab, setTab] = useState(0);
  const t = tour[tab];
  const onKey = (e: React.KeyboardEvent) => {
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!d) return;
    const n = (tab + d + tour.length) % tour.length;
    setTab(n);
    document.getElementById(`tab-${tour[n].id}`)?.focus();
  };
  return (
    <section className="tour" aria-labelledby="tour-h">
      <div className="section-head">
        <h2 id="tour-h">One screen for the whole process</h2>
        <p><code>aiw ui</code> starts every stage as a headless session and keeps score across your repos. Local, stdlib Python, no accounts.</p>
      </div>
      <div className="tabs" role="tablist" aria-label="UI screens" onKeyDown={onKey}>
        {tour.map((x, i) => (
          <button
            key={x.id}
            id={`tab-${x.id}`}
            role="tab"
            aria-selected={i === tab}
            aria-controls="tour-panel"
            tabIndex={i === tab ? 0 : -1}
            onClick={() => setTab(i)}
          >
            {x.label}
          </button>
        ))}
      </div>
      <div className="tour-panel" id="tour-panel" role="tabpanel" aria-labelledby={`tab-${t.id}`}>
        <div className="tour-text">
          <h3>{t.title}</h3>
          <p>{t.body}</p>
        </div>
        <Window title={`aiw ui · ${t.label}`}>
          <Media key={t.id} {...t.media} alt={t.title} />
        </Window>
      </div>
    </section>
  );
}

function Run() {
  return (
    <section className="run" id="run" aria-labelledby="run-h">
      <div className="section-head">
        <h2 id="run-h">A real run: {run.feature}</h2>
        <p>{run.summary}</p>
      </div>
      <dl className="stats">
        {run.stats.map((s) => (
          <div key={s.label}>
            <dt>{s.label}</dt>
            <dd>{s.value}</dd>
          </div>
        ))}
      </dl>
      <Window title={`${run.repo} · full run, sped up`}>
        <Media kind="video" {...run.video} alt="The full run, sped up with captions per stage" />
      </Window>
    </section>
  );
}

export function App() {
  return (
    <>
      <Hero />
      <main>
        <Pipeline />
        <Tour />
        <Run />
        <section className="end">
          <h2>Bring your next idea.</h2>
          <p>Install the plugin in Claude Code, point it at a repo, and run <code>aiw ui</code>.</p>
          <StarLink big />
        </section>
      </main>
      <footer>
        Built by <a href="https://github.com/masnun-siam">Masnun Siam</a>. Runs on Claude Code.
      </footer>
    </>
  );
}
