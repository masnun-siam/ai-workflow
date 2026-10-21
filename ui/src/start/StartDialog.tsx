import { useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import { api } from '../api/endpoints';
import { keys, useApiMutation, useOpenItems, usePeerReviewOffers, useRepos, useSessions, useSettings } from '../api/hooks';
import type { Session } from '../api/types';
import { Banner, Button, Dialog, toast } from '../components';
import { clockText } from '../lib/format';
import { routes } from '../lib/routes';
import { COMMAND, COMMANDS, lensName } from '../lib/vocab';
import { CreateRepoDialog } from '../repos/CreateRepoDialog';
import { useRepo } from '../shell/useRepo';
import { FolderChooser } from './FolderChooser';
import { ARG_HINT, ARG_LABEL, LineInput, OpenPicker, prdArg, PrdInput, TextInput, WorklogInput } from './Inputs';
import { CMD_KEY, folderOf, isoDay, limitedUntil, NO_REPO, OPTIONAL, PICK, repoFromText, startBody, switchArgs, worklogDates, type FolderPick, type WhereSel, type WorklogPick } from './startLogic';
import type { StartPreset } from './StartContext';
import { Where } from './Where';
import './start.css';

const read = (k: string) => {
  try {
    return localStorage.getItem(k) || '';
  } catch {
    return '';
  }
};
const write = (k: string, v: string) => {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* storage blocked: the dialog still works */
  }
};
const initialCommand = (preset: StartPreset) => [preset.cmd, read(CMD_KEY)].find((c) => c && COMMAND[c]) ?? 'create-prd';

/** The Start dialog (FR-22): pick a command, say where it runs and what on, then start it as a session. */
export function StartDialog({ open, preset, onClose }: { open: boolean; preset: StartPreset; onClose: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="Start something" description="Pick a command and what it runs on." wide bare>
      <StartBody preset={preset} onClose={onClose} />
    </Dialog>
  );
}

function StartBody({ preset, onClose }: { preset: StartPreset; onClose: () => void }) {
  const nav = useNavigate();
  const { repo: curRepo } = useRepo();
  const repos = useRepos();
  const settings = useSettings();
  const sessions = useSessions();
  const offers = usePeerReviewOffers();
  const start = useApiMutation<Parameters<typeof api.startSession>[0], Session>(api.startSession, [['sessions'], ['inbox'], ['session']], { quiet: true });

  const [cmd, setCmd] = useState(() => initialCommand(preset));
  const [arg, setArg] = useState(preset.arg ?? '');
  const [sel, setSel] = useState<WhereSel | null>(preset.repo ? { kind: 'repo', slug: preset.repo } : null);
  const [vf, setVf] = useState<FolderPick>({ project: '', feature: '', touched: false });
  const [acctSel, setAcctSel] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [wl, setWl] = useState<WorklogPick>({ mode: 'today', day: '', from: '', to: '' });
  const [failedDays, setFailedDays] = useState<string[] | null>(null);
  const [progress, setProgress] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [dup, setDup] = useState('');
  const [creating, setCreating] = useState(false);

  const c = COMMAND[cmd];
  const repoList = repos.data?.repos ?? [];
  const canVault = NO_REPO.has(cmd);
  const defaultSlug = preset.repo || curRepo || repoList[0]?.slug || '';
  const repoSel: WhereSel = defaultSlug ? { kind: 'repo', slug: defaultSlug } : { kind: 'path', path: '' };
  let where: WhereSel = sel ?? (!defaultSlug && canVault ? { kind: 'vault' } : repoSel);
  if (where.kind === 'vault' && !canVault) where = repoSel; // this command needs a repo
  const slug = where.kind === 'repo' ? where.slug : '';

  // The open issue / PR list and the approved PRDs belong to the picked repo.
  const pick = PICK[cmd];
  const listable = !!pick && slug.includes('/') && !slug.startsWith('local/');
  const openQ = useOpenItems(slug, pick ?? 'issue', listable);
  const prds = useQuery({ queryKey: keys.planning(slug), queryFn: () => api.planning(slug), enabled: c.arg === 'prd' && listable });
  const approved = (prds.data?.prds ?? []).filter((p) => p.status === 'Approved');

  const cmds = settings.data?.commands ?? [];
  const acct = acctSel ?? settings.data?.default ?? '';
  const until = limitedUntil(cmds, acct, sessions.data?.limits);

  const offer = offers.data?.kinds?.[cmd] ?? [];
  const lenses = offer.filter((l) => picked.includes(l));

  const today = isoDay(new Date());
  const days = c.arg === 'day' ? worklogDates(wl, today) : null;
  const dayError = days && 'error' in days ? days.error : '';
  const argText = c.arg === 'prd' ? prdArg(arg) : arg;
  const repoOk = where.kind === 'repo' ? !!where.slug : where.kind === 'path' ? !!where.path.trim() : true;
  const argOk = c.arg === 'none' || c.arg === 'day' || OPTIONAL.has(cmd) || !!argText.trim();
  const valid = repoOk && argOk && !dayError;
  const folderText = c.arg === 'text' ? arg : '';

  const changeArg = (v: string) => {
    setArg(v);
    setErr('');
    const hit = repoFromText(repoList, v); // a pasted issue / PR URL of a registered repo switches the repo
    if (hit && hit !== slug) setSel({ kind: 'repo', slug: hit });
  };
  const changeCmd = (id: string) => {
    setArg(switchArgs(c, COMMAND[id], arg, slug, openQ.data?.items ?? []));
    setCmd(id);
    setErr('');
    setFailedDays(null);
  };

  const finish = (s: Session) => {
    write(CMD_KEY, cmd);
    onClose();
    nav(routes.session(s.id));
  };
  const fail = (e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    setErr(msg);
    if (e instanceof ApiError && e.duplicate?.id) {
      const id = e.duplicate.id;
      setDup(id);
      toast.error(msg, { action: { label: 'Open that run', onClick: () => { onClose(); nav(routes.session(id)); } } });
    }
  };
  const body = (args: string, batch?: string) =>
    startBody({ where, folder: folderOf(vf), command: cmd, args, lenses, account: acct || undefined, batch });

  // Worklog: one run, or one per day of a range. A range shares a batch id, so the server runs 3 at a time.
  const runWorklog = async () => {
    const dates = failedDays ?? (days && 'dates' in days ? days.dates : []);
    if (dates.length === 1 && !failedDays) return finish(await start.mutateAsync(body(dates[0])));
    const batch = `wl-${Date.now().toString(36)}`;
    const failed: { date: string; why: string }[] = [];
    let ok = 0;
    for (const [i, date] of dates.entries()) {
      setProgress(`Starting ${i + 1} of ${dates.length}…`);
      try {
        await start.mutateAsync(body(date, batch));
        ok++;
      } catch (e) {
        failed.push({ date, why: e instanceof Error ? e.message : 'failed' });
      }
    }
    setProgress('');
    setFailedDays(failed.length ? failed.map((f) => f.date) : null);
    if (failed.length) setErr(`${failed.length} of ${dates.length} did not start: ${failed.map((f) => `${f.date} (${f.why})`).join('; ')}`);
    if (ok) {
      write(CMD_KEY, cmd);
      toast(`Started ${ok} worklog run${ok === 1 ? '' : 's'}, 3 at a time`);
      if (!failed.length) {
        onClose();
        nav(routes.activity);
      }
    }
  };

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setErr('');
    setDup('');
    try {
      if (cmd === 'worklog') await runWorklog();
      else finish(await start.mutateAsync(body(argText)));
    } catch (er) {
      fail(er);
    } finally {
      setBusy(false);
    }
  };

  const label = busy ? progress || 'Starting…' : failedDays?.length ? `Retry ${failedDays.length} failed day${failedDays.length === 1 ? '' : 's'}` : until ? 'Queue' : 'Start';

  return (
    <>
      <div className="start">
        <nav className="start-list" aria-label="Commands">
          {COMMANDS.map((g) => (
            <div key={g.g} role="group" aria-label={g.g}>
              <div className="g" aria-hidden="true">{g.g}</div>
              {g.items.map((x) => (
                <button key={x.id} type="button" className={cmd === x.id ? 'on' : ''} aria-pressed={cmd === x.id} onClick={() => changeCmd(x.id)}>
                  <div style={{ fontWeight: 600 }}>{x.name}</div>
                  <div className="s">{x.id === 'custom' ? 'any prompt' : `/${x.id}`}</div>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <form className="start-form" onSubmit={submit} noValidate aria-label={`${c.name} options`}>
          <div className="start-fields">
            <div>
              <h2 style={{ fontSize: 18 }}>{c.name}</h2>
              <p className="muted">{c.desc}</p>
            </div>
            <Where
              repos={repoList}
              value={where}
              onChange={(w) => { setSel(w); setErr(''); }}
              canVault={canVault}
              canBrowse={repos.data?.can_browse === true}
              vaultFolder={vf}
              onCreate={() => setCreating(true)}
            />
            {where.kind === 'vault' ? <FolderChooser text={folderText} value={vf} onChange={setVf} /> : null}

            {c.arg === 'text' ? (
              <TextInput id="start-arg" label={ARG_LABEL[cmd]} placeholder={c.placeholder} value={arg} onChange={changeArg} onSubmit={() => void submit()} />
            ) : c.arg === 'issue' || c.arg === 'pr' ? (
              <OpenPicker id="start-arg" command={cmd} kind={c.arg} value={arg} onChange={changeArg} q={openQ} slug={slug} usable={listable} placeholder={ARG_HINT[cmd] ?? ''} />
            ) : c.arg === 'issues' ? (
              <LineInput id="start-arg" label={ARG_LABEL[cmd]} hint="Numbers, #numbers or URLs." placeholder={ARG_HINT[cmd]} value={arg} onChange={changeArg} />
            ) : c.arg === 'prd' ? (
              <PrdInput id="start-arg" prds={approved} value={arg} onChange={changeArg} />
            ) : c.arg === 'day' ? (
              <WorklogInput value={wl} onChange={(v) => { setWl(v); setFailedDays(null); setErr(''); }} error={wl.mode !== 'range' || wl.from || wl.to ? dayError : ''} />
            ) : (
              <LineInput id="start-arg" label={ARG_LABEL[cmd] ?? 'Options (optional)'} placeholder={ARG_HINT[cmd]} value={arg} onChange={changeArg} />
            )}

            {offer.length > 0 ? (
              <div className="lbl">
                <span id="start-lenses">Peer review</span>
                <span className="hint">
                  Optional. Each picked lens must approve, up to {offers.data?.max_rounds ?? 5} rounds, on Opus.
                  {cmd === 'custom' ? " The session is asked to run the review when it's done; it isn't forced." : ''}
                </span>
                <div className="lens-row" role="group" aria-labelledby="start-lenses">
                  {offer.map((l) => (
                    <button key={l} type="button" className={`lens${lenses.includes(l) ? ' on' : ''}`} aria-pressed={lenses.includes(l)} onClick={() => setPicked(lenses.includes(l) ? lenses.filter((x) => x !== l) : [...lenses, l])}>
                      {lensName(l)}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {cmd === 'custom' ? (
              <Banner tone="review" icon="alert">
                <p>Custom prompts run with permission checks skipped (--dangerously-skip-permissions): the prompt is not gated.</p>
              </Banner>
            ) : null}

            {cmds.length > 1 ? (
              <div className="lbl">
                <span id="start-run-on">Run on</span>
                <div className="seg" role="radiogroup" aria-labelledby="start-run-on">
                  {cmds.map((a) => {
                    const lim = limitedUntil(cmds, a.label, sessions.data?.limits);
                    return (
                      <button key={a.label} type="button" role="radio" aria-checked={acct === a.label} className={acct === a.label ? 'on' : ''} title={lim ? `Limited until ${clockText(lim)}` : undefined} onClick={() => setAcctSel(a.label)}>
                        {a.label}{lim ? ' · limited' : ''}
                      </button>
                    );
                  })}
                </div>
                {until ? <span className="hint" style={{ color: 'var(--review)' }}>This account is limited until {clockText(until)}. The session queues and starts at reset.</span> : null}
              </div>
            ) : until ? (
              <p className="hint" style={{ color: 'var(--review)' }}>This account is limited until {clockText(until)}. The session queues and starts at reset.</p>
            ) : null}

            <div aria-live="polite">
              {err ? (
                <p className="err-text" role="alert">
                  {err}{' '}
                  {dup ? <button type="button" className="linkish" style={{ color: 'var(--accent)', fontWeight: 600 }} onClick={() => { onClose(); nav(routes.session(dup)); }}>Open that run</button> : null}
                </p>
              ) : null}
            </div>
          </div>
          <div className="d-f">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="primary" type="submit" disabled={!valid || busy}>{label}</Button>
          </div>
        </form>
      </div>
      <CreateRepoDialog
        open={creating}
        onClose={() => setCreating(false)}
        vaultFolder={where.kind === 'vault' ? folderOf(vf) ?? undefined : undefined}
        onCreated={(r) => setSel({ kind: 'repo', slug: r.slug })}
      />
    </>
  );
}
