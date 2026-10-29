// FR-7, FR-8, FR-10 and the Away summary (FR-26): everything that needs the user, across repos.
import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAfkDismiss, useInbox, useRepos, useSessions, needsYouCount } from '../api/hooks';
import type { AfkLogEntry, AfkState } from '../api/types';
import { Banner, Button, Chip, EmptyState, useListSelection } from '../components';
import type { InboxItem } from '../api/types';
import { usePanel, type PanelTarget } from '../panels/PanelContext';
import { ChangeDialog, type RoundEntry } from '../inbox/ChangeDialog';
import { ItemRow, useInboxActions } from '../inbox/items';
import { clockText, money, shortRepo } from '../lib/format';
import { mdToHtml } from '../lib/md';
import { displayLabel } from '../questions/QuestionForm';
import { RepoSelect } from '../shell/RepoSelect';
import { routes } from '../lib/routes';
import { INBOX_GROUPS } from '../lib/vocab';
import { PublishDialog } from '../repos/PublishDialog';

const KIND: Record<string, string> = { answer: 'Answered', 'skip-ci': 'Skipped CI', retry: 'Retried' };

type RichEntry = AfkLogEntry & { id: string };
const isRich = (l: AfkLogEntry): l is RichEntry => !!l.id && (l.kind === 'answer' || l.kind === 'held');
const hhmm = (t: number) => clockText(t);
const byGroup = (list: InboxItem[]) => INBOX_GROUPS.flatMap(({ id }) => list.filter((i) => i.group === id));
/** `items` in the order of `keys` (the order last shown); items not in it keep the server order after the known ones of their group. */
function heldOrder(items: InboxItem[], keys: string[]): InboxItem[] {
  const at = new Map(keys.map((k, n) => [k, n]));
  return byGroup([...items].sort((x, y) => (at.get(x.key) ?? keys.length) - (at.get(y.key) ?? keys.length)));
}

function RoundRow({ l, checked, onToggle }: { l: RichEntry; checked: boolean; onToggle: () => void }) {
  const held = l.kind === 'held';
  const opus = held || l.by === 'opus';
  const qs = l.questions ?? [];
  return (
    <li style={{ listStyle: 'none' }}>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {!held && !l.changed ? (
          <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`Change answer: ${qs[0]?.question ?? l.command}`} />
        ) : null}
        <span className="faint">{hhmm(l.at)}</span>
        <Link to={routes.session(l.sid)}>{l.command}</Link>
        <Chip tone={held ? 'you' : opus ? 'review' : 'ship'}>{held ? 'Held' : opus ? 'Opus' : 'Recommended'}</Chip>
        {l.changed ? <Chip tone="muted">Changed</Chip> : null}
        {opus ? <span className="muted">{money(l.cost)}</span> : null}
        {opus && l.answerer ? <Link to={routes.session(l.answerer)}>answerer transcript</Link> : null}
        {typeof l.risk === 'number' ? <span className="muted">Risk check: sent to Opus (p={+l.risk.toFixed(2)})</span> : null}
      </div>
      <div className="stack" style={{ gap: 4, paddingLeft: 24 }}>
        {qs.map((q, k) => (
          <div key={k}>
            <div className="prose" dangerouslySetInnerHTML={{ __html: mdToHtml(q.question) }} />
            {!held && q.picked ? <div>→ {q.picked.map(displayLabel).join(', ')}{opus && q.why ? <span className="muted"> “{q.why}”</span> : null}</div> : null}
          </div>
        ))}
        {held && l.reason ? <div className="muted">“{l.reason}”</div> : null}
      </div>
    </li>
  );
}

function AwaySummary({ s }: { s: NonNullable<AfkState['summary']> }) {
  const dismiss = useAfkDismiss();
  const log = s.log ?? [];
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // ticks for ids that vanished or got changed on a refetch are ignored
  const changeable = new Set(log.filter((l) => isRich(l) && l.kind === 'answer' && !l.changed).map((l) => l.id));
  const ticked = [...selected].filter((id) => changeable.has(id));
  const [changing, setChanging] = useState(false);
  const rounds = log.filter((l): l is RoundEntry => isRich(l) && !!l.questions && ticked.includes(l.id));
  const toggle = (id: string) => setSelected((p) => { const n = new Set(p); if (!n.delete(id)) n.add(id); return n; });
  const held = log.filter((l) => l.kind === 'held').length || s.held;
  const handled = log.filter((l) => l.kind !== 'held').length;
  return (
    <Banner tone="away" icon="moon" action={<>{ticked.length ? <Button sm onClick={() => setChanging(true)}>Change {ticked.length} selected</Button> : null}<Button sm shortcut="x" onClick={() => dismiss.mutate()}>Dismiss</Button></>}>
      <div className="stack" style={{ gap: 8 }}>
        <p>
          <b>While you were away ({clockText(s.started)}{s.ended ? `–${clockText(s.ended)}` : ''}): {handled} handled, {held} held</b>
        </p>
        {log.length ? (
          <ul style={{ margin: 0, paddingLeft: 0 }}>
            {log.map((l, k) =>
              isRich(l) ? (
                <RoundRow key={l.id} l={l} checked={selected.has(l.id)} onToggle={() => toggle(l.id)} />
              ) : (
                <li key={k} style={{ marginLeft: 18 }}>
                  {l.at ? <span className="faint">{clockText(l.at)} </span> : null}
                  {KIND[l.kind ?? ''] ?? l.kind} {l.sid ? <Link to={routes.session(l.sid)}>{l.command ?? 'session'}</Link> : l.command}
                  {l.picked ? <span className="muted"> · {l.picked}</span> : null}
                </li>
              ),
            )}
          </ul>
        ) : null}
      </div>
      {changing && rounds.length ? <ChangeDialog rounds={rounds} onClose={() => setChanging(false)} /> : null}
    </Banner>
  );
}

/** The PR or issue the panel shows for a row; none for rows that have neither (FR-5). */
function panelTargetOf(it: InboxItem | undefined): PanelTarget | null {
  if (!it?.repo) return null;
  if ('pr' in it && typeof it.pr === 'number') return { kind: 'pr', repo: it.repo, n: it.pr };
  if ('issue' in it && typeof it.issue === 'number') return { kind: 'issue', repo: it.repo, n: it.issue };
  return null;
}

export function InboxPage() {
  const [filter, setFilter] = useState('');
  const q = useInbox(filter || undefined);
  const repos = useRepos().data?.repos ?? [];
  const sessions = useSessions().data?.sessions ?? [];
  const a = useInboxActions();
  const [openKey, setOpen] = useState<string | null | undefined>(undefined);
  const [publishing, setPublishing] = useState('');
  const panel = usePanel();
  const shown = useRef<string[]>([]);

  const items = q.data?.items ?? [];
  const count = needsYouCount(items);
  const working = sessions.filter((s) => s.outcome === 'starting' || s.outcome === 'running').length;
  // FR-4: while a row or the side panel is open, rows keep the order last shown; a new order applies once nothing is open
  const opened = openKey === undefined ? items.some((i) => i.type === 'question') : items.some((i) => i.key === openKey);
  const ordered = opened || panel.target ? heldOrder(items, shown.current) : byGroup(items);
  shown.current = ordered.map((i) => i.key);
  const firstAnswer = ordered.find((i) => i.type === 'question')?.key ?? null;
  const open = openKey === undefined ? firstAnswer : openKey;
  const afk = q.data?.afk;
  // Enter is registered per row (ItemRow), so the list's own handler has nothing to do.
  const { selected, rowProps } = useListSelection({ keys: ordered.map((i) => i.key), onOpen: () => {}, reset: filter, panelTarget: (k) => panelTargetOf(ordered.find((i) => i.key === k)) });

  return (
    <div className="content-inner">
      <div className="page-head">
        <div className="grow">
          <h1>Inbox</h1>
          <p className="sub">
            {count ? `${count} thing${count === 1 ? '' : 's'} need${count === 1 ? 's' : ''} you${filter ? '' : ' across your repos'}. ` : 'Nothing needs you. '}
            {working === 1 ? '1 session is working on its own.' : `${working} sessions are working on their own.`}
          </p>
        </div>
        {afk?.active ? <Chip tone="away">Away mode: Claude answers every question</Chip> : null}
        <RepoSelect repos={repos} value={filter} onChange={setFilter} label="Repo filter" width={180} extrasBefore={[{ value: '', label: 'All repos' }]} />
      </div>
      {afk?.summary ? <AwaySummary s={afk.summary} /> : null}
      {q.isError ? (
        <Banner tone="bad" icon="alert" action={<Button sm onClick={() => void q.refetch()}>Retry</Button>}>Could not load the inbox. {q.error.message}</Banner>
      ) : null}
      {q.data?.stale?.length ? (
        <Banner tone="muted" icon="clock">
          GitHub data for {q.data.stale.length} repo{q.data.stale.length === 1 ? '' : 's'} is still loading, so merge-ready PRs may be missing.
          {q.data.stale.length <= 3 ? (
            <> ({q.data.stale.map(shortRepo).join(', ')})</>
          ) : (
            <details><summary>Which repos</summary>{q.data.stale.map(shortRepo).join(', ')}</details>
          )}
        </Banner>
      ) : null}
      {q.isLoading ? <div className="skel" style={{ height: 120 }} /> : null}
      {q.data && !count ? (
        <EmptyState icon="inbox" title="All clear" actions={<Link className="btn" to={routes.activity}>See what is running</Link>}>
          Questions, approvals, merges and failures show up here the moment they need you. {working === 1 ? '1 session is working.' : `${working} sessions are working.`}
        </EmptyState>
      ) : null}
      {INBOX_GROUPS.map(({ id, label }) => {
        const g = ordered.filter((i) => i.group === id);
        if (!g.length) return null;
        return (
          <section key={id} aria-label={label}>
            <div className="group-h"><h2>{label}</h2><span className="n">{g.length}</span></div>
            <div className="list">
              {g.map((it) => (
                <ItemRow key={it.key} item={it} a={a} open={open === it.key} toggle={() => setOpen(open === it.key ? null : it.key)} publish={setPublishing} selected={selected === it.key} rowProps={rowProps(it.key)} autoFocus={openKey !== undefined} />
              ))}
            </div>
          </section>
        );
      })}
      <PublishDialog open={!!publishing} slug={publishing} onClose={() => setPublishing('')} />
    </div>
  );
}
