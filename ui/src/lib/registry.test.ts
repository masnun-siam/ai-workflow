import { render, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useRegistry } from '../api/hooks';
import { QueryProvider } from '../QueryProvider';
import { REGISTRY, primeRegistry } from '../test-registry';
import { commandOf, isStep, setRegistry, STEP, type Registry } from './registry';

describe('registry', () => {
  afterEach(() => { setRegistry({}); vi.unstubAllGlobals(); });

  it('commandOf returns the entry command, or empty for an unknown step', () => {
    primeRegistry();
    expect(commandOf(STEP.writePrd)).toBe('/blubird:create-prd');
    expect(commandOf('nope')).toBe('');
    expect(commandOf(STEP.writePrd, {})).toBe('');
  });

  it('isStep matches the skill in any prefix spelling, and nothing else', () => {
    primeRegistry();
    for (const c of ['/blubird:implement-issue 1', '/ai-workflow:implement-issue 1', '/implement-issue 1']) expect(isStep(c, STEP.implement)).toBe(true);
    expect(isStep('/implement-issue 1', STEP.afterMerge)).toBe(true); // two steps share a skill
    expect(isStep('implement issue 1', STEP.implement)).toBe(false);
    expect(isStep('/implement-issue-y 1', STEP.implement)).toBe(false);
    expect(isStep('/implement-issue 1', 'nope')).toBe(false);
  });

  it('swapping one entry changes that step only', () => {
    const swapped: Registry = { ...REGISTRY.steps, [STEP.refine]: { ...REGISTRY.steps[STEP.refine], plugin: 'ai-workflow', command: '/ai-workflow:refine-issues' } };
    setRegistry(swapped);
    expect(commandOf(STEP.refine)).toBe('/ai-workflow:refine-issues');
    for (const id of Object.values(STEP)) if (id !== STEP.refine) expect(commandOf(id)).toBe(REGISTRY.steps[id].command);
  });

  it('the fixture covers every STEP', () => {
    for (const id of Object.values(STEP)) expect(REGISTRY.steps[id]?.command).toMatch(/^\/[\w-]+:[\w-]+$/);
  });

  it('useRegistry loads the registry once and fills commandOf', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(REGISTRY), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    const Probe = () => { useRegistry(); useRegistry(); return null; };
    render(createElement(QueryProvider, null, createElement(Probe)));
    await waitFor(() => expect(commandOf(STEP.implement)).toBe('/blubird:implement-issue'));
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('useRegistry reports a failed load without throwing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"error":"boom"}', { status: 500, headers: { 'Content-Type': 'application/json' } })));
    let state: ReturnType<typeof useRegistry> | undefined;
    const Probe = () => { state = useRegistry(); return null; };
    render(createElement(QueryProvider, null, createElement(Probe)));
    await waitFor(() => expect(state?.isError).toBe(true), { timeout: 10_000 });
    expect(commandOf(STEP.implement)).toBe('');
  });
});
