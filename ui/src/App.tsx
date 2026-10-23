import { HashRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { useRepos } from './api/hooks';
import { ConfirmProvider } from './components';
import { ActivityPage } from './pages/ActivityPage';
import { DispatchPage } from './pages/DispatchPage';
import { DispatchesPage } from './pages/DispatchesPage';
import { FeaturePage } from './pages/FeaturePage';
import { FeaturesPage } from './pages/FeaturesPage';
import { InboxPage } from './pages/InboxPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { OnboardingPage } from './pages/OnboardingPage';
import { SessionPage } from './pages/SessionPage';
import { SettingsPage } from './pages/SettingsPage';
import { PanelProvider } from './panels/PanelContext';
import { QueryProvider } from './QueryProvider';
import { Shell } from './shell/Shell';
import { OtherIssuesPage } from './pages/OtherIssuesPage';
import { StartProvider } from './start/StartContext';

/** No registered repos: everything but Settings sends the user to onboarding (FR-29). */
function Gate() {
  const { pathname } = useLocation();
  const repos = useRepos();
  const empty = repos.isSuccess && repos.data.repos.length === 0;
  if (empty && !pathname.startsWith('/settings') && pathname !== '/onboarding') return <Navigate to="/onboarding" replace />;
  return <Outlet />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route element={<Gate />}>
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/features" element={<FeaturesPage />} />
          <Route path="/features/:slug" element={<FeaturePage />} />
          <Route path="/features/:slug/:tab" element={<FeaturePage />} />
          <Route path="/" element={<Navigate to="/inbox" replace />} />
          <Route path="/issues" element={<OtherIssuesPage />} />
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
