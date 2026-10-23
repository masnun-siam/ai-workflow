import { describe, expect, it } from 'vitest';
import { folderOf, grindPr, keywordSuggest, limitedUntil, matchItems, repoFromText, startBody, switchArgs, typedNumber, worklogDates } from './startLogic';

const where = { kind: 'repo', slug: 'o/r' } as const;
const base = { where, folder: null, lenses: [] as string[] };

describe('start request bodies', () => {
  it('named command: repo, command, args', () => {
    expect(startBody({ ...base, command: 'implement-issue', args: ' 12 ' })).toEqual({ repo: 'o/r', command: 'implement-issue', args: '12' });
  });
  it('custom prompt sends text; lenses go as peer_review; the account as claude_cmd', () => {
    expect(startBody({ ...base, command: 'implement-issue', args: '1', model: 'opus', effort: 'max' })).toMatchObject({ model: 'opus', effort: 'max' });
    expect(Object.keys(startBody({ ...base, command: 'implement-issue', args: '1', model: null, effort: null }))).not.toContain('model');
    expect(startBody({ ...base, command: 'custom', args: 'do it', lenses: ['critical'], account: 'Masum' })).toEqual({ repo: 'o/r', text: 'do it', peer_review: ['critical'], claude_cmd: 'Masum' });
  });
  it('no repo yet: no_repo + vault_folder and an empty repo', () => {
    const w = { kind: 'vault' } as const;
    expect(startBody({ ...base, where: w, folder: '05-Work/Gym/Check-ins', command: 'create-prd', args: 'idea' })).toEqual({ repo: '', no_repo: true, vault_folder: '05-Work/Gym/Check-ins', command: 'create-prd', args: 'idea' });
    expect(startBody({ ...base, where: w, command: 'dump', args: 'x' })).toEqual({ repo: '', no_repo: true, command: 'dump', args: 'x' });
  });
  it('pr-grind carries the PR as issue; worklog batch is passed through', () => {
    expect(startBody({ ...base, command: 'pr-grind', args: 'https://github.com/o/r/pull/7' }).issue).toBe(7);
    expect(startBody({ ...base, command: 'implement-issue', args: '7' }).issue).toBeUndefined();
    expect(startBody({ ...base, command: 'worklog', args: '2026-10-01', batch: 'wl-x' }).batch).toBe('wl-x');
  });
  it('a typed path is the repo', () => {
    expect(startBody({ ...base, where: { kind: 'path', path: ' /a/b ' }, command: 'release-pr', args: '' }).repo).toBe('/a/b');
  });
});

describe('worklog days', () => {
  const t = '2026-10-21';
  it('today and yesterday pass through; a range lists each day', () => {
    expect(worklogDates({ mode: 'today', day: '', from: '', to: '' }, t)).toEqual({ dates: ['today'] });
    expect(worklogDates({ mode: 'range', day: '', from: '2026-09-29', to: '2026-10-02' }, t)).toEqual({ dates: ['2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02'] });
  });
  it('rejects bad ranges', () => {
    expect(worklogDates({ mode: 'range', day: '', from: '2026-10-05', to: '2026-10-01' }, t)).toHaveProperty('error');
    expect(worklogDates({ mode: 'range', day: '', from: '2026-08-01', to: '2026-10-01' }, t)).toEqual({ error: 'Pick at most 31 days' });
    expect(worklogDates({ mode: 'day', day: '2027-01-01', from: '', to: '' }, t)).toHaveProperty('error');
  });
});

describe('arguments', () => {
  it('typedNumber, grindPr, matchItems', () => {
    expect(typedNumber('#12')).toBe(12);
    expect(typedNumber('https://github.com/o/r/issues/9')).toBe(9);
    expect(typedNumber('words')).toBeNull();
    expect(grindPr('https://github.com/o/r/issues/9')).toBeNull();
    const items = [{ number: 12, title: 'Fix login', labels: ['bug'], updated_at: '', draft: false, url: null }, { number: 130, title: 'Docs', labels: [], updated_at: '', draft: false, url: null }];
    expect(matchItems(items, '13').map((i) => i.number)).toEqual([130]);
    expect(matchItems(items, 'login').map((i) => i.number)).toEqual([12]);
  });
  it('repoFromText finds a registered repo from a URL', () => {
    const repos = [{ slug: 'o/r' }, { slug: 'o/other' }];
    expect(repoFromText(repos, 'see https://github.com/O/Other/pull/4')).toBe('o/other');
    expect(repoFromText(repos, 'https://github.com/x/y/issues/1')).toBeNull();
  });
  it('switchArgs: same kind carries over, rewritten per command; other kinds clear', () => {
    const rev = { id: 'pr-review', arg: 'pr' } as const;
    const grind = { id: 'pr-grind', arg: 'pr' } as const;
    const items = [{ number: 5, title: 't', labels: [], updated_at: '', draft: false, url: 'https://github.com/o/r/pull/5' }];
    expect(switchArgs(rev, grind, '5', 'o/r', items)).toBe('https://github.com/o/r/pull/5');
    expect(switchArgs(grind, rev, 'https://github.com/o/r/pull/5', 'o/r', items)).toBe('5');
    expect(switchArgs(rev, grind, 'https://github.com/x/y/pull/5', 'o/r', items)).toBe('https://github.com/x/y/pull/5');
    expect(switchArgs({ id: 'dump', arg: 'text' }, { id: 'create-prd', arg: 'text' }, 'an idea', '', [])).toBe('an idea');
    expect(switchArgs({ id: 'dump', arg: 'text' }, rev, 'an idea', '', [])).toBe('');
  });
});

describe('vault folder and limits', () => {
  it('folderOf and keywordSuggest', () => {
    expect(folderOf({ project: 'Gym App', feature: 'Check-ins' })).toBe('05-Work/Gym App/Check-ins');
    expect(folderOf({ project: '', feature: 'x' })).toBeNull();
    const folders = [{ project: 'Gym App', feature: null }, { project: 'Gym App', feature: 'Member check-ins' }, { project: 'Recipes', feature: null }];
    expect(keywordSuggest(folders, 'gym members checking in')[0]).toMatchObject({ project: 'Gym App', feature: 'Member check-ins' });
  });
  it('limitedUntil is set only while the account is limited', () => {
    const cmds = [{ label: 'Masum', cmd: 'cc masum' }];
    expect(limitedUntil(cmds, 'Masum', { 'cc masum': { limited_until: 2000 } }, 1000)).toBe(2000);
    expect(limitedUntil(cmds, 'Masum', { 'cc masum': { limited_until: 500 } }, 1000)).toBeNull();
    expect(limitedUntil(cmds, 'Nope', {}, 1000)).toBeNull();
  });
});
