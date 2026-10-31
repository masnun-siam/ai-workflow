import '@fontsource-variable/chivo/wght.css';
import '@fontsource-variable/chivo-mono/wght.css';
import './styles/global.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { migrateRepoKey } from './lib/repo';

migrateRepoKey();

// The offline-page service worker stays at the server root (ui/public/sw.js).
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch((e) => console.warn('aiw: service worker not registered', e));
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
