import '@fontsource-variable/archivo/wdth.css';
import '../styles/global.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { SharePage } from './SharePage';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SharePage />
  </StrictMode>,
);
