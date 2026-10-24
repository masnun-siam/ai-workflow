import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/endpoints';
import { Button, toast } from '../components';
import './settings.css';

const POLL_MS = 2000;

/** Server: runs the repo's `make restart` (rebuild the UI, restart the supervisord server) and reloads once it succeeds. */
export function ServerSection() {
  const [started, setStarted] = useState(false);
  const [err, setErr] = useState('');
  // A failed poll (server down mid-restart) keeps the last data, so it still counts as "running".
  const status = useQuery({ queryKey: ['restart'], queryFn: api.restartStatus, retry: false, refetchInterval: started ? POLL_MS : false });
  const s = status.data;
  const running = started && (status.isError || !s || s.running || s.exit_code === null);
  const failed = s !== undefined && !s.running && s.exit_code !== null && s.exit_code !== 0;

  useEffect(() => {
    if (!started || status.isError || !s || s.running || s.exit_code === null) return;
    setStarted(false);
    if (s.exit_code === 0) {
      toast('Restarted. Reloading…');
      location.reload();
    }
  }, [started, status.isError, s]);

  const onClick = async () => {
    setErr('');
    try {
      await api.restart();
      await status.refetch();
      setStarted(true);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const unavailable = s !== undefined && !s.available;
  return (
    <section className="set-sec" aria-labelledby="set-server-h">
      <div>
        <h2 id="set-server-h">Server</h2>
        <p className="muted">Runs <code>make restart</code> in the plugin checkout: rebuilds the UI, restarts the <code>aiw-ui</code> server, and reloads this page when it is back.</p>
        {unavailable ? <p className="muted">No <code>make restart</code> target in this install.</p> : null}
      </div>
      <div>
        <Button variant="primary" disabled={unavailable || running || !s} onClick={() => void onClick()}>{running ? 'Restarting…' : 'Rebuild and restart'}</Button>
      </div>
      {err ? <p className="err-text" role="alert">{err}</p> : null}
      {failed && !running ? (
        <div role="alert">
          <p className="err-text">Restart failed (exit {s.exit_code}).</p>
          <pre className="mono">{s.log_tail}</pre>
        </div>
      ) : null}
    </section>
  );
}
