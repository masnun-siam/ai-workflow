import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { TabPanel, Tabs } from './Tabs';

const tabs = [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }, { value: 'c', label: 'C' }];
function Harness({ pageKeys }: { pageKeys?: boolean }) {
  const [v, setV] = useState('a');
  return (
    <>
      <input aria-label="field" />
      <Tabs value={v} onValueChange={setV} tabs={tabs} pageKeys={pageKeys}>
        {tabs.map((t) => <TabPanel key={t.value} value={t.value}>{t.label} body</TabPanel>)}
      </Tabs>
    </>
  );
}
const sel = (n: string) => screen.getByRole('tab', { name: n }).getAttribute('aria-selected');

afterEach(cleanup);

describe('Tabs pageKeys', () => {
  it('steps with ] and [ and stops at the ends', async () => {
    const u = userEvent.setup();
    render(<Harness pageKeys />);
    await u.keyboard('[[');
    expect(sel('A')).toBe('true');
    await u.keyboard(']]');
    expect(sel('C')).toBe('true');
    await u.keyboard(']');
    expect(sel('C')).toBe('true');
    await u.keyboard('[[');
    expect(sel('B')).toBe('true');
  });
  it('ignores keys typed in a field, with a modifier, or a dialog open', async () => {
    const u = userEvent.setup();
    render(<Harness pageKeys />);
    await u.click(screen.getByLabelText('field'));
    await u.keyboard(']');
    expect(sel('A')).toBe('true');
    (document.activeElement as HTMLElement).blur();
    await u.keyboard('{Control>}]{/Control}');
    expect(sel('A')).toBe('true');
    const d = document.body.appendChild(document.createElement('div'));
    d.setAttribute('role', 'dialog');
    await u.keyboard(']');
    expect(sel('A')).toBe('true');
    d.remove();
  });
  it('does nothing without pageKeys', async () => {
    const u = userEvent.setup();
    render(<Harness />);
    await u.keyboard(']');
    expect(sel('A')).toBe('true');
  });
});
