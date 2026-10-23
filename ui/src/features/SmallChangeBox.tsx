import { useState } from 'react';
import { Button } from '../components';
import { useStarter } from '../board/actions';
import { PLAN_RUN } from '../lib/vocab';
import { smallChangeArg } from './smallChange';

/** Starts one headless /create-tasks session for a bug or small change with no PRD. */
export function SmallChangeBox({ repo }: { repo: string }) {
  const [text, setText] = useState('');
  const starter = useStarter();
  const create = async () => {
    const id = await starter.startBoard({ repo, skill: 'create-tasks', arg: smallChangeArg(text), via: 'headless', ...PLAN_RUN }, { nav: false });
    if (id) setText('');
  };
  return (
    <div className="empty" style={{ borderStyle: 'solid' }}>
      <label htmlFor="small-change"><strong>Describe a bug or small change</strong></label>
      <textarea id="small-change" className="f" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row wrap">
        <Button variant="primary" disabled={!text.trim() || starter.pending} onClick={create}>Create task</Button>
      </div>
    </div>
  );
}
