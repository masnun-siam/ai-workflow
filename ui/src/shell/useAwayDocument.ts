import { useEffect } from 'react';
import { useSessions } from '../api/hooks';

/** Away mode tints the rail: <html data-away> while it is on. */
export function useAwayDocument() {
  const on = !!useSessions().data?.afk?.active;
  useEffect(() => {
    if (on) document.documentElement.dataset.away = '';
    else delete document.documentElement.dataset.away;
  }, [on]);
}
