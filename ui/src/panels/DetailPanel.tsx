import { useEffect, useRef, type ReactNode } from 'react';
import { Button, Icon } from '../components';
import { WorkPanel } from './WorkPanel';
import { KeyScope } from '../shell/shortcuts';
import { usePanel } from './PanelContext';

/** Header + scrolling body + optional sticky footer. Panels use it so they all look and close the same way. */
export function PanelFrame({ title, subtitle, head, footer, children }: { title: ReactNode; subtitle?: ReactNode; head?: ReactNode; footer?: ReactNode; children: ReactNode }) {
  const { close } = usePanel();
  return (
    <>
      <div className="p-head">
        <div className="row">
          <h2 className="grow ellipsis">{title}</h2>
          <Button variant="ghost" icon sm noAction aria-label="Close panel" onClick={close}><Icon n="x" /></Button>
        </div>
        {subtitle ? <div className="muted ellipsis" style={{ fontSize: 12.5 }}>{subtitle}</div> : null}
        {head}
      </div>
      <div className="p-body">{children}</div>
      {footer ? <div className="p-foot">{footer}</div> : null}
    </>
  );
}

/**
 * The right column. Rendered by the shell inside `.app.has-panel`: a grid column on wide screens,
 * a fixed overlay below 1180 px and full screen below 760 px (CSS). Focus moves in on open.
 */
export function DetailPanel() {
  const { target, follow, close } = usePanel();
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (target && !follow) ref.current?.focus({ preventScroll: true });
  }, [target?.kind, target?.repo, target?.n]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!target) return null;
  const key = `${target.kind}:${target.repo}#${target.n}`;
  return (
    <>
      <div className="panel-scrim" onClick={close} aria-hidden="true" />
      <aside className="panel" aria-label={target.kind === 'issue' ? 'Issue details' : 'Pull request details'} tabIndex={-1} ref={ref}>
        <KeyScope level="panel" active>
          <WorkPanel key={key} kind={target.kind} repo={target.repo} n={target.n} />
        </KeyScope>
      </aside>
    </>
  );
}
