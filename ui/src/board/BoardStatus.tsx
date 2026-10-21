import type { BoardMeta } from '../api/types';
import { Banner } from '../components';
import { clockText, untilText } from '../lib/format';
import { GhBanner } from '../shell/Banners';

/** Banners shared by Features and Board (FR-30): gh signed out, rate limit with data age, stale data. */
export function BoardStatus({ meta, failed }: { meta?: BoardMeta; failed?: boolean }) {
  const limited = !!meta?.retry_at && meta.retry_at * 1000 > Date.now();
  return (
    <>
      <GhBanner />
      {limited && meta ? (
        <Banner tone="review" icon="clock">
          <p>
            <b>GitHub rate limit reached.</b>
            {meta.fetched_at ? ` Showing data from ${clockText(meta.fetched_at)}.` : ''} Refreshing again {untilText(meta.retry_at!)}.
          </p>
          <p className="muted">Starting sessions still works. Board data may be out of date.</p>
        </Banner>
      ) : meta && (meta.stale || meta.error) ? (
        <Banner tone="review" icon="clock">
          <p>
            <b>This data may be out of date.</b>
            {meta.fetched_at ? ` Last fetched at ${clockText(meta.fetched_at)}.` : ' It has not been fetched yet.'}
            {meta.error ? ` ${meta.error}` : ''}
          </p>
        </Banner>
      ) : failed ? (
        <Banner tone="bad" icon="wifi"><p><b>Could not refresh.</b> Showing the last data. Retrying.</p></Banner>
      ) : null}
    </>
  );
}

export const isRateLimited = (meta?: BoardMeta) => !!meta?.retry_at && meta.retry_at * 1000 > Date.now();
