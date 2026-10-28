import { HashRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { useRepos } from './api/hooks';
import { ConfirmProvider } from './components';
import { ActivityPage } from './pages/ActivityPage';
import { DispatchPage } from './pages/DispatchPage';
import { DispatchesPage } from './pages/DispatchesPage';
import { FeaturePage } from './pages/FeaturePage';
import { FeaturesPage } from './pages/FeaturesPage';
import { InboxPage } from './pages/InboxPage';
import { NewPage } from './pages/NewPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { OnboardingPage } from './pages/OnboardingPage';
import { SessionPage } from './pages/SessionPage';
import { SettingsPage } from './pages/SettingsPage';
import { SmallChangesPage } from './pages/SmallChangesPage';
import { PanelProvider } from './panels/PanelContext';
import { QueryProvider } from './QueryProvider';
import { Shell } from './shell/Shell';
import { routes } from './lib/routes';
import { StartProvider } from './start/StartContext';

/** No registered repos: everything but Settings sends the user to onboarding (FR-29). */
function Gate() {
  const { pathname } = useLocation();
  const repos = useRepos();
  const empty = repos.isSuccess && repos.data.repos.length === 0;
  if (empty && !pathname.startsWith('/settings') && pathname !== '/onboarding') return <Navigate to="/onboarding" replace />;
  return <Outlet />;
}

/** The old Other issues page and the old Features → Small changes tab are the Small changes page. */
function ChangesRedirect() {
  const { search } = useLocation();
  const p = new URLSearchParams(search);
  p.delete('tab');
  const q = p.toString();
  return <Navigate to={{ pathname: routes.changes, search: q ? `?${q}` : '' }} replace />;
}

/** Features, unless an old link asks for its Small changes tab. */
function FeaturesRoute() {
  const { search } = useLocation();
  return new URLSearchParams(search).get('tab') === 'changes' ? <ChangesRedirect /> : <FeaturesPage />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route element={<Gate />}>
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/features" element={<FeaturesRoute />} />
          <Route path="/changes" element={<SmallChangesPage />} />
          <Route path="/new" element={<NewPage />} />
          <Route path="/features/:slug" element={<FeaturePage />} />
          <Route path="/features/:slug/:tab" element={<FeaturePage />} />
          <Route path="/" element={<Navigate to="/inbox" replace />} />
          <Route path="/issues" element={<ChangesRedirect />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/dispatches" element={<DispatchesPage />} />
          <Route path="/dispatches/:id" element={<DispatchPage />} />
          <Route path="/sessions/:id" element={<SessionPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/settings/:section" element={<SettingsPage />} />
          <Route path="/onboarding" element={<OnboardingPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <QueryProvider>
      <ConfirmProvider>
        <HashRouter>
          <PanelProvider>
            <StartProvider>
              <AppRoutes />
            </StartProvider>
          </PanelProvider>
        </HashRouter>
      </ConfirmProvider>
    </QueryProvider>
  );
}
