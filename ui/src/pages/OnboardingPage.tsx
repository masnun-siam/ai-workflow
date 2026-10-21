import { useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRepos, useScanRepos, useSessions, useSettings } from '../api/hooks';
import type { ScanResult } from '../api/types';
import { Button, Icon, type IconName } from '../components';
import { routes } from '../lib/routes';

function Check({ ok, icon, title, children }: { ok: boolean | null; icon?: IconName; title: string; children?: ReactNode }) {
  const tone = ok === true ? 't-ship' : ok === false ? 't-you' : 't-accent';
  return (
    <div className="item">
      <div className={`item-ico ${tone}`}><Icon n={icon ?? (ok === true ? 'check' : ok === false ? 'alert' : 'clock')} /></div>
      <div className="stack" style={{ gap: 8 }}>
        <div>
          <div className="item-title">{title}</div>
          <div className="item-meta">{children}</div>
        </div>
      </div>
      <div />
    </div>
  );
}

/** First run (FR-29): GitHub CLI signed in, a Claude account, then scan folders for repos. The shell sends users here while no repo is registered. */
export function OnboardingPage() {
  const nav = useNavigate();
  const sessions = useSessions();
  const settings = useSettings();
  const repos = useRepos();
  const scan = useScanRepos();
  const [roots, setRoots] = useState<string | null>(null);
  const [found, setFound] = useState<ScanResult | null>(null);

  const gh = sessions.data?.gh;
  const ghOk = gh ? gh.ok : null;
  const account = settings.data?.commands?.[0];
  const rootText = roots ?? (repos.data?.scan_roots ?? []).join('\n');
  const total = repos.data?.repos.length ?? 0;

  const find = async () => {
    try {
      const folders = rootText.split('\n').map((s) => s.trim()).filter(Boolean);
      setFound((await scan.mutateAsync(folders)) as unknown as ScanResult);
    } catch {
      /* toasted */
    }
  };

  return (
    <div className="content-inner" style={{ maxWidth: 720 }}>
      <div>
        <h1>Set up aiw</h1>
        <p className="muted" style={{ marginTop: 4 }}>Two checks, then pick the folders your repositories live in.</p>
      </div>
      <div className="list">
        <Check ok={ghOk} title={ghOk === false ? 'GitHub CLI is not signed in' : ghOk ? 'GitHub CLI signed in' : 'Checking the GitHub CLI…'}>
          {ghOk ? (gh?.login ? `as ${gh.login}` : 'gh is ready.') : ghOk === false ? <>Run <code>gh auth login</code> in a terminal, then come back. {gh?.error ? <span>({gh.error})</span> : null}</> : null}
        </Check>
        <Check ok={settings.isSuccess ? !!account : null} title={account ? 'Claude account found' : settings.isSuccess ? 'No Claude account yet' : 'Checking Claude…'}>
          {account ? <><code>{account.cmd}</code> is set up as “{account.label}”. Add more accounts in Settings.</> : settings.isSuccess ? 'Add one in Settings: a command that starts Claude, like claude.' : null}
        </Check>
        <div className="item">
          <div className="item-ico t-accent"><Icon n="folder" /></div>
          <div className="stack" style={{ gap: 10 }}>
            <div>
              <div className="item-title">Add your repositories</div>
              <div className="item-meta">Folders to look in, one per line. Every git checkout with a GitHub origin is registered.</div>
            </div>
            <label className="sr" htmlFor="onb-roots">Folders to scan</label>
            <textarea id="onb-roots" className="f mono" rows={3} spellCheck={false} value={rootText} onChange={(e) => setRoots(e.target.value)} />
            {found ? (
              <div className="stack" style={{ gap: 6 }} role="status">
                {found.added.length ? (
                  <>
                    <b>Added {found.added.length} {found.added.length === 1 ? 'repository' : 'repositories'}</b>
                    {found.added.map((r) => (
                      <div key={r.slug} className="row"><Icon n="check" s={14} /><span className="mono">{r.slug}</span><span className="muted ellipsis mono">{r.path}</span></div>
                    ))}
                  </>
                ) : (
                  <p className="muted">{total ? 'No new repos found.' : 'No repos found in those folders. Check the paths, or clone a repo there first.'}</p>
                )}
              </div>
            ) : null}
            <div className="row wrap">
              <Button variant={found?.added.length ? 'default' : 'primary'} onClick={() => void find()} disabled={scan.isPending || !rootText.trim()}>
                <Icon n="search" />{scan.isPending ? 'Scanning…' : found ? 'Scan again' : 'Find repos'}
              </Button>
              {total > 0 ? <Button variant="primary" onClick={() => nav(routes.inbox)}>Done: open the Inbox</Button> : null}
            </div>
          </div>
          <div />
        </div>
      </div>
    </div>
  );
}
