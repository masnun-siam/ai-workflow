import { LinkButton } from '../components';
import { routes } from '../lib/routes';

export function NotFoundPage() {
  return (
    <div className="content-inner">
      <div className="page-head">
        <div className="grow">
          <h1>Page not found</h1>
          <p className="sub">This address does not match a page in aiw.</p>
        </div>
      </div>
      <div><LinkButton to={routes.inbox} variant="primary">Back to Inbox</LinkButton></div>
    </div>
  );
}
