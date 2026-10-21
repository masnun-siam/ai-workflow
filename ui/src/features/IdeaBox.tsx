import { useState } from 'react';
import { Button } from '../components';
import { useStarter } from '../board/actions';
import { useStart } from '../start/StartContext';

/** FR-17: a repo with no PRDs. Starts /create-prd, or the Start dialog for the notes vault. */
export function IdeaBox({ repo, name }: { repo: string; name: string }) {
  const [text, setText] = useState('');
  const starter = useStarter();
  const start = useStart();
  return (
    <div className="empty" style={{ borderStyle: 'solid' }}>
      <h2>No features in {name} yet</h2>
      <p className="muted" style={{ maxWidth: '60ch' }}>Describe what you want to build. Claude asks you questions, writes the PRD, and it shows up here as a draft.</p>
      <label className="sr" htmlFor="idea">Describe the feature</label>
      <textarea id="idea" className="f" rows={4} placeholder="Example: Let admins import users from a CSV, with a preview of errors before anything is saved." value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row wrap">
        <Button variant="primary" disabled={!text.trim() || starter.pending} onClick={() => starter.startSession({ repo, command: 'create-prd', args: text.trim() })}>Write the PRD</Button>
        <span className="muted" style={{ fontSize: 13 }}>
          Not tied to a repo yet? Pick “No repo yet” in{' '}
          <button type="button" className="linkish" style={{ textDecoration: 'underline' }} onClick={() => start.open({ cmd: 'create-prd', arg: text, repo: 'vault' })}>New</button>{' '}
          to write it in your notes vault.
        </span>
      </div>
    </div>
  );
}
