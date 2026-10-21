import { EmptyState, LinkButton } from '../components';
import { routes } from '../lib/routes';

export function NotFoundPage() {
  return (
    <div className="content-inner">
      <EmptyState icon="alert" title="Page not found" actions={<LinkButton to={routes.inbox} variant="primary">Back to Inbox</LinkButton>}>
        This address does not match a page in aiw.
      </EmptyState>
    </div>
  );
}
