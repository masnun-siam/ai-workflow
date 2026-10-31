import { Command } from 'cmdk';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAfkStart, useAfkStop, useOpenItems, usePlanning, useSessions } from '../api/hooks';
import { sessionLabel } from '../lib/format';
import { routes } from '../lib/routes';
import { COMMAND_LIST, ISSUE, SESS, STAGES } from '../lib/vocab';
import { joinFeatures, snapshotsReady } from '../lib/features';
import { useDelivery } from '../api/hooks';
import { usePanel } from '../panels/PanelContext';
import { useRepo } from '../shell/useRepo';
import { useCreate } from '../create/Create';
import { useStart } from '../start/StartContext';
import { LEVEL_RANK, useActions } from '../shell/shortcuts';

interface Entry {
  id: string;
  group: string;
  label: string;
  right?: string;
  run: () => void;
}

const GROUP_ORDER = ['Actions here', 'Open', 'Go to', 'Start', 'Features', 'Issues', 'Pull requests', 'Sessions', 'Switch repo', 'Away'];

/** ⌘K (FR-4). Rendered by the shell only while open, so its queries run only then. */
export function Palette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const { repo, repos, setRepo, link } = useRepo();
  const start = useStart();
  const create = useCreate();
  const panel = usePanel();
  const [q, setQ] = useState('');
  const planning = usePlanning(repo).data;
  const delivery = useDelivery(repo).data;
  const issues = useOpenItems(repo, 'issue').data?.items ?? [];
  const prs = useOpenItems(repo, 'pr').data?.items ?? [];
  const sessions = useSessions().data;
  const afkStart = useAfkStart();
  const afkStop = useAfkStop();
  const afk = sessions?.afk;
  const actions = useActions();

  const all = useMemo<Entry[]>(() => {
    const e: Entry[] = [];
    const ranked = actions.filter((a) => !a.disabled).sort((a, b) => LEVEL_RANK[b.level] - LEVEL_RANK[a.level] || a.seq - b.seq);
    for (const a of ranked) {
      e.push({ id: `act:${a.seq}`, group: 'Actions here', label: `${a.name ? `${a.name}: ` : ''}${a.label}${a.key ? ` (${a.key.toUpperCase()})` : ''}`, run: a.run });
    }
    const go = (path: string) => () => navigate(link(path));
    for (const [path, label] of [[routes.inbox, 'Inbox'], [routes.features, 'Features'], [routes.dispatches, 'Dispatches'], [routes.activity, 'Activity'], [routes.settings(), 'Settings']] as const) {
      e.push({ id: `go:${path}`, group: 'Go to', label, run: go(path) });
    }
    e.push({ id: 'new', group: 'Start', label: 'New feature or small change', right: 'N', run: () => create.open({ repo }) });
    for (const c of COMMAND_LIST) e.push({ id: `cmd:${c.id}`, group: 'Start', label: c.name, right: `/${c.id}`, run: () => start.open({ cmd: c.id, repo }) });
    if (planning && snapshotsReady(planning, delivery)) {
      for (const f of joinFeatures(planning.prds, delivery?.lanes ?? [])) e.push({ id: `f:${f.slug}`, group: 'Features', label: f.title, right: STAGES.find((s) => s.id === f.stage)?.label, run: () => navigate(link(routes.feature(f.slug))) });
    } else if (planning) {
      for (const p of planning.prds) e.push({ id: `f:${p.slug}`, group: 'Features', label: p.title, right: p.status, run: () => navigate(link(routes.feature(p.slug))) });
    }
    for (const i of issues) {
      const card = delivery?.lanes.flatMap((l) => l.cards).find((c) => c.n === i.number);
      e.push({ id: `i:${i.number}`, group: 'Issues', label: `#${i.number} ${i.title}`, right: card ? ISSUE[card.column].label : undefined, run: () => panel.open({ kind: 'issue', repo, n: i.number }) });
    }
    for (const p of prs) e.push({ id: `p:${p.number}`, group: 'Pull requests', label: `#${p.number} ${p.title}`, right: p.draft ? 'Draft' : 'PR', run: () => panel.open({ kind: 'pr', repo, n: p.number }) });
    for (const s of sessions?.sessions ?? []) e.push({ id: `s:${s.id}`, group: 'Sessions', label: sessionLabel(s.command), right: SESS[s.outcome]?.label, run: () => navigate(routes.session(s.id)) });
    for (const r of repos) if (r.slug !== repo) e.push({ id: `r:${r.slug}`, group: 'Switch repo', label: r.name, right: r.slug, run: () => setRepo(r.slug) });
    e.push(
      afk?.active
        ? { id: 'away:off', group: 'Away', label: "I'm back (turn off Away mode)", run: () => afkStop.mutate() }
        : { id: 'away:on', group: 'Away', label: 'Go away for 2 hours', run: () => afkStart.mutate(Math.floor(Date.now() / 1000) + 7200) },
    );
    return e;
  }, [planning, delivery, issues, prs, sessions, repos, repo, afk?.active, actions]); // eslint-disable-line react-hooks/exhaustive-deps

  const results = useMemo(() => {
    const t = q.trim().toLowerCase();
    const num = /^#?(\d+)$/.exec(t);
    const out: Entry[] = [];
    if (num && repo) {
      const n = Number(num[1]);
      // a typed number always offers its issue and its PR, even if the open lists have not loaded or it is closed
      out.push({ id: `open:i:${n}`, group: 'Open', label: `Issue #${n}`, right: repo, run: () => panel.open({ kind: 'issue', repo, n }) });
      out.push({ id: `open:p:${n}`, group: 'Open', label: `Pull request #${n}`, right: repo, run: () => panel.open({ kind: 'pr', repo, n }) });
    }
    const rest = t ? all.filter((x) => `${x.group} ${x.label} ${x.right ?? ''}`.toLowerCase().includes(t.replace(/^#/, ''))) : all;
    // a number that matches an issue already shows it under Issues; keep the exact-match rows first
    const seen = new Set(out.map((o) => o.id));
    return [...out, ...rest.filter((x) => !seen.has(x.id))].slice(0, 60);
  }, [q, all, repo]); // eslint-disable-line react-hooks/exhaustive-deps

  const groups = [...new Set(results.map((r) => r.group))].sort((a, b) => GROUP_ORDER.indexOf(a) - GROUP_ORDER.indexOf(b));
  const run = (x: Entry) => {
    onClose();
    x.run();
  };
  return (
    <Command.Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      label="Search"
      shouldFilter={false}
      loop
      overlayClassName="scrim-r"
      contentClassName="dialog dlg-pos pal pal-c"
    >
      <Command.Input value={q} onValueChange={setQ} placeholder="Search features, issues, sessions, or start something…" aria-label="Search" autoFocus />
      <Command.List>
        {results.length === 0 ? <Command.Empty>Nothing matches “{q}”.</Command.Empty> : null}
        {groups.map((g) => (
          <Command.Group key={g} heading={g}>
            {results.filter((r) => r.group === g).map((x) => (
              <Command.Item key={x.id} value={x.id} onSelect={() => run(x)}>
                <span className="ellipsis">{x.label}</span>
                {x.right ? <span className="r">{x.right}</span> : null}
              </Command.Item>
            ))}
          </Command.Group>
        ))}
      </Command.List>
    </Command.Dialog>
  );
}
