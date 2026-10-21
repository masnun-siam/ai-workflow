import { Link, useParams } from 'react-router-dom';
import { routes } from '../lib/routes';
import { useRepo } from '../shell/useRepo';
import { AccountsSection } from '../settings/AccountsSection';
import { NotificationsSection } from '../settings/NotificationsSection';
import { ReposSection } from '../settings/ReposSection';
import { ReviewSection } from '../settings/ReviewSection';
import { VaultSection } from '../settings/VaultSection';

export const SECTIONS = [
  { id: 'repos', label: 'Repositories', Body: ReposSection },
  { id: 'accounts', label: 'Claude accounts', Body: AccountsSection },
  { id: 'notifications', label: 'Notifications', Body: NotificationsSection },
  { id: 'review', label: 'Peer review', Body: ReviewSection },
  { id: 'vault', label: 'Notes vault', Body: VaultSection },
] as const;
const ALIAS: Record<string, string> = { commands: 'accounts', notify: 'notifications' }; // old settings links

export const sectionOf = (s: string | undefined) => {
  const id = ALIAS[s ?? ''] ?? s;
  return SECTIONS.find((x) => x.id === id)?.id ?? 'repos';
};

/** Settings (FR-28). Route #/settings/<section>. Every section saves on its own and stays mounted, so unsaved edits survive a tab switch. */
export function SettingsPage() {
  const cur = sectionOf(useParams().section);
  const { link } = useRepo();
  return (
    <div className="content-inner">
      <div className="page-head"><h1>Settings</h1></div>
      <div className="set-grid">
        <nav className="set-nav" aria-label="Settings sections">
          {SECTIONS.map((s) => (
            <Link key={s.id} to={link(routes.settings(s.id))} className={`nav-a${cur === s.id ? ' on' : ''}`} aria-current={cur === s.id ? 'page' : undefined}>
              {s.label}
            </Link>
          ))}
        </nav>
        <div>
          {SECTIONS.map(({ id, Body }) => (
            <div key={id} hidden={id !== cur}><Body /></div>
          ))}
        </div>
      </div>
    </div>
  );
}
