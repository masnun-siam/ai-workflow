(function () {
  const CFG = Object.assign({ layout: 'drawer', skins: ['console'] }, window.SETU_CFG || {});
  const SCREENS = [['river', 'River'], ['inbox', 'Inbox'], ['runs', 'Runs'], ['releases', 'Releases'], ['ops', 'Ops'], ['me', 'Me'], ['settings', 'Settings']];
  const PRODUCTS = ['Wasensi', 'BOP BD', 'Deshi Commerce'];

  // id -> card. need = waiting on you. ask = question with options. acts = [key, label, toast, clearsNeed]
  const C = {
    'prd-kyc': { t: 'Merchant KYC re-check', m: 'draft · wasensi-docs', tag: 'draft', tc: 'c-w', skill: 'blubird:create-prd', repo: 'wasensi-docs',
      log: ['Interview 6 of 11 questions answered', 'Paused 2 days ago'], acts: [['o', 'Continue interview', 'Resumed blubird:create-prd']] },
    'prd-pay': { t: 'Merchant payouts v2', m: '9 tasks planned', tag: 'approve', tc: 'c-w', need: true, kind: 'Approval', skill: 'blubird:create-prd', repo: 'wasensi-docs',
      log: ['PRD written: docs/prds/payouts/batches.md', 'Technical design settled', 'Waiting for approval'],
      acts: [['e', 'Approve + create epic', 'Approved. Epic created in wasensi-docs', true], ['o', 'Read PRD', 'Opens the PRD']] },
    'ep-941': { t: 'Courier rate cache', m: 'epic #941 · 5 issues', tag: 'epic', tc: 'c-q', skill: 'blubird:create-tasks', repo: 'wasensi-docs',
      log: ['5 child issues with blocked-by links'], acts: [['f', 'Refine all 5', 'Started blubird:refine-issues 941']] },
    i1044: { t: '#1044 CSV drops VAT', m: 'bug · reproducing', tag: 'bug', tc: 'c-b', live: true, skill: 'blubird:reproduce-bug', repo: 'wasensi-backend',
      log: ['Timeline built from the issue + 2 Slack threads', 'Top cause: export column map since #998', 'Reproducing locally…'], acts: [['o', 'Open session', 'Opens transcript']] },
    i1015: { t: '#1015 Statement PDF', m: 'Backlog', tag: 'backlog', tc: '', skill: '—', repo: 'wasensi-web', acts: [['f', 'Refine', 'Started blubird:refine-issues 1015']] },
    i1012: { t: '#1012 Payout batch model', m: '38m · $4.12', tag: 'question', tc: 'c-q', need: true, kind: 'Question', skill: 'blubird:implement-issue', repo: 'wasensi-backend',
      log: ['Worktree issue-1012-payout-batch from staging', 'Failing test PayoutBatchTest written', 'hook · 2 secrets masked', 'Asked you 4m ago'],
      ask: { q: 'Migration adds NOT NULL payout_batch_id to orders (2.1M rows). How do existing rows get a value?', o: ['Nullable + backfill job', 'Backfill in migration', 'Legacy batch default'] },
      acts: [['o', 'Open session', 'Opens transcript'], ['x', 'Stop', 'Stopped #1012']] },
    i1013: { t: '#1013 Batch scheduler', m: 'CI running · 22m', tag: 'ci', tc: 'c-q', live: true, skill: 'blubird:implement-issue', repo: 'wasensi-backend',
      log: ['Draft PR #1041 opened', 'Peer review: 2 lenses passed', 'CI running (3/5 jobs)'], acts: [['o', 'Open session', 'Opens transcript']] },
    i1031: { t: '#1031 Retry on 429', m: 'Ready', tag: 'ready', tc: 'c-o', skill: '—', repo: 'wasensi-backend',
      acts: [['i', 'Implement', 'Started blubird:implement-issue 1031'], ['d', 'Add to dispatch', 'Added to dispatch lane 2']] },
    i1019: { t: '#1019 Slow search', m: 'PR #1029 · 3 comments', tag: 'review', tc: 'c-w', skill: 'blubird:pr-review', repo: 'wasensi-backend',
      log: ['2 human comments, 1 bot comment'], acts: [['x', 'Fix comments', 'Started blubird:pr-review --fix #1029'], ['g', 'Grind', 'Started pr-grind on #1029']] },
    i1033: { t: '#1033 Dashboard status', m: 'grind round 2 · CI ✓', tag: 'grind', tc: 'c-o', live: true, skill: 'pr-grind', repo: 'wasensi-web',
      log: ['Round 1: 3 findings, 2 fixed, 1 rebutted', 'Round 2 requested from copilot'], acts: [['o', 'Open PR', 'Opens PR #1035']] },
    'rel-web': { t: 'wasensi-web', m: '6 PRs on staging', tag: 'release', tc: '', skill: 'release-pr', repo: 'wasensi-web',
      acts: [['r', 'Cut release', 'Started release-pr in wasensi-web'], ['y', 'Dry run', 'release-pr --dry-run']] },
    'rel-1040': { t: 'Release PR #1040', m: 'grind round 3', tag: 'grind', tc: 'c-q', live: true, skill: 'pr-grind', repo: 'wasensi-backend',
      log: ['release-pr: 14 PRs, deploy checklist, 1 migration', 'Slack trigger posted', 'Round 3 waiting on the bot'], acts: [['o', 'Open thread', 'Opens Slack thread']] },
    'rel-1036': { t: 'Release #1036', m: 'merged 20m ago', tag: 'notify', tc: 'c-w', need: true, kind: 'Release', skill: 'release-note', repo: 'wasensi-backend',
      note: '@here\n🚀 Release Note — 12 November 2026\nMerchants can now see payouts grouped into weekly batches.\n\nPayouts\n• Weekly batches with one statement each\n\nCC: @Ashique vai, @Najmul vai, @Abir vai',
      acts: [['p', 'Post to #dc-supports', 'Posted once to #dc-supports', true], ['e', 'Edit note', 'Editing'], ['x', 'Skip', 'Skipped', true]] },
    i455: { t: '#455 phpstan failed', m: 'bop-bd · 12m ago', tag: 'failed', tc: 'c-b', need: true, kind: 'Failed', skill: 'blubird:verifier-locally', repo: 'bop-bd',
      log: ['RateCache.php:41 missing return type', 'RateCache.php:77 undefined method get()', 'RateCacheTest.php:12 unused $rate'],
      acts: [['f', 'Resume with fix', 'Resumed #455 with a fix prompt', true], ['o', 'Open session', 'Opens transcript']] },
    coord: { t: 'Coordinator · label:payments', m: 'bop-bd · 4/5 slots', tag: 'running', tc: 'c-q', live: true, skill: 'blubird:project-coordinator', repo: 'bop-bd',
      log: ['#455 verifying', '#458 PR open, review comments', '#461 implementing', '#462 implementing'], acts: [['x', 'Stop refilling', 'Coordinator will not refill']] },
    sweep: { t: 'Security sweep · weekly', m: 'done · 3 fix actions', tag: 'done', tc: 'c-o', skill: 'blubird:security-sweep', repo: 'wasensi-docs',
      log: ['14 repos scanned', '1 known-exploited (KEV)', '3 tickets filed'], acts: [['o', 'Open tickets', 'Opens 3 security tickets']] },
  };
  const STAGES = [
    { n: 'PRD', k: 'create-prd · map-prds', cards: ['prd-kyc', 'prd-pay'] },
    { n: 'Tasks', k: 'create-tasks', cards: ['ep-941'] },
    { n: 'Refine', k: 'refine-issues · reproduce-bug', cards: ['i1044', 'i1015'] },
    { n: 'Implement', k: 'implement-issue · coordinator', cards: ['i1012', 'i1013', 'i1031'] },
    { n: 'Review', k: 'pr-review · peer · grind', cards: ['i1019', 'i1033'] },
    { n: 'Release', k: 'release-pr · pr-grind', cards: ['rel-web', 'rel-1040'] },
    { n: 'Notify', k: 'release-note', cards: ['rel-1036'] },
  ];
  const RUNS = [['i1012', '38m', '$4.12'], ['i1013', '22m', '$2.30'], ['rel-1040', '1h04', '$3.88'], ['coord', '2h10', '$6.80'], ['i455', '6m', '$0.41'], ['i1044', '9m', '$0.77'], ['sweep', '14m', '$1.20']];
  const OPS = [
    ['blubird:agentic-onboard', 'each repo', '5/6 repos ready · dc-store-front missing'],
    ['blubird:map-prds', 'docs repo', 'Deshi Commerce · 7 drafts to refine'],
    ['blubird:ci-optimize', 'each repo', 'wasensi-backend not measured'],
    ['blubird:security-sweep', 'docs repo', 'last 10 Nov · 3 fix actions'],
    ['blubird:docs-updater', 'each repo', '41 commits since last run'],
    ['blubird:skill-feedback', 'any repo', '12 PRs since last reconcile'],
  ];
  const SKILLS = [['blubird:create-prd', 'docs repo'], ['blubird:create-tasks', 'docs repo'], ['blubird:refine-issues', 'issue repo'], ['blubird:implement-issue', 'issue repo'],
    ['blubird:reproduce-bug', 'issue repo'], ['blubird:verifier-locally', 'issue repo'], ['blubird:pr-review', 'issue repo'], ['blubird:project-coordinator', 'any'],
    ['blubird:docs-updater', 'each repo'], ['blubird:security-sweep', 'docs repo'], ['blubird:day-end-reconcile', 'anywhere'], ['blubird:weekly-review', 'anywhere'],
    ['release-pr', 'built in'], ['pr-grind', 'built in'], ['release-note', 'built in'], ['peer-review', 'built in']];

  const S = { screen: 'river', st: 3, ci: 0, sel: { inbox: 0, runs: 0, ops: 0 }, open: null, pal: false, palQ: '', palI: 0, help: false,
    skin: CFG.skins[0], theme: 'system', layout: CFG.layout, toast: '', rel: 3, noteOpen: true, product: 0 };
  const PREF_KEY = 'setu-appearance';
  if (CFG.remember) { try { Object.assign(S, JSON.parse(localStorage.getItem(PREF_KEY) || '{}')); } catch (e) { /* storage blocked: defaults */ } }
  function savePrefs() { if (!CFG.remember) return; try { localStorage.setItem(PREF_KEY, JSON.stringify({ skin: S.skin, theme: S.theme, layout: S.layout })); } catch (e) { /* ignore */ } }
  const APPEAR = [
    ['skin', 'Look', [['console', 'Console', 'mono, amber, boxed panes'], ['river', 'River', 'navy, rounded cards']], 's'],
    ['theme', 'Mode', [['system', 'System', 'follow macOS'], ['dark', 'Dark', ''], ['light', 'Light', '']], '.'],
    ['layout', 'Layout', [['drawer', 'Rail + drawer', 'details slide in over the page'], ['split', 'Tabs + split', 'detail pane always visible']], 'L'],
  ];
  function vAppearance() {
    return `<div class="pane" style="grid-column:1/-1"><div class="lb">appearance</div><div class="det">${APPEAR.map((g) =>
      `<div class="seg-row"><span class="seg-l">${g[1]} <kbd>${g[3]}</kbd></span><div class="seg" role="radiogroup" aria-label="${g[1]}">${g[2].map((o) =>
        `<button class="seg-o${S[g[0]] === o[0] ? ' on' : ''}" role="radio" aria-checked="${S[g[0]] === o[0]}" data-a="pref:${g[0]}:${o[0]}"><b>${o[1]}</b>${o[2] ? `<span>${o[2]}</span>` : ''}</button>`).join('')}</div></div>`).join('')}
      <span class="dim">Saved on this browser. Combine any look with any layout and mode.</span></div></div>`;
  }

  const inboxIds = () => Object.keys(C).filter((id) => C[id].need);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  function cur() {
    if (S.screen === 'river') return STAGES[S.st].cards[S.ci];
    if (S.screen === 'inbox') return inboxIds()[S.sel.inbox];
    if (S.screen === 'runs') return (RUNS[S.sel.runs] || [])[0];
    return null;
  }
  const target = () => S.open || (S.layout === 'split' ? cur() : null);
  function toast(m) { S.toast = m; clearTimeout(toast.t); toast.t = setTimeout(() => { S.toast = ''; render(); }, 2600); }
  function answer(id, i) { const c = C[id]; c.need = false; c.log = (c.log || []).concat('You answered: ' + c.ask.o[i]); c.m = 'continuing'; c.tag = 'running'; c.tc = 'c-q'; c.live = true; toast('Answered "' + c.ask.o[i] + '". ' + c.t.split(' ')[0] + ' continues'); render(); }
  function act(id, i) { const a = C[id].acts[i]; if (a[3]) { C[id].need = false; C[id].tag = 'done'; C[id].tc = 'c-o'; } toast(a[2]); render(); }
  function go(s) { S.screen = s; S.open = null; render(); }

  // ---------- views ----------
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  function card(id, si, ci) {
    const c = C[id]; const sel = S.screen === 'river' && si === S.st && ci === S.ci;
    return `<button class="card${c.need ? ' need' : ''}${sel ? ' sel' : ''}" data-a="card:${si}:${ci}"><span class="t">${esc(c.t)}</span><span class="m"><span class="tag ${c.tc}">${c.tag}</span>${esc(c.m)}</span>${c.live ? '<span class="live" aria-hidden="true"></span>' : ''}</button>`;
  }
  function vRiver() {
    return `<div class="pane"><div class="lb">river · ${PRODUCTS[S.product].toLowerCase()}</div><div class="river">${STAGES.map((s, si) =>
      `<div class="stage${s.cards.some((id) => C[id].need) ? ' hot' : ''}${si === S.st ? ' cur' : ''}"><div class="sh"><b>${s.n}</b><span>${s.k}</span></div>${s.cards.map((id, ci) => card(id, si, ci)).join('')}</div>`).join('')}</div></div>`;
  }
  function vInbox() {
    const ids = inboxIds();
    return `<div class="pane"><div class="lb">inbox · ${ids.length} need you</div><div class="rows">${ids.map((id, i) => { const c = C[id];
      return `<button class="row${i === S.sel.inbox ? ' sel' : ''}" data-a="isel:${i}"><span class="tag ${c.tc}">${c.kind}</span><span class="t">${esc(c.t)}</span><span class="w">${c.repo}</span></button>`; }).join('') || '<div class="empty">Nothing needs you.</div>'}</div></div>`;
  }
  function vRuns() {
    return `<div class="pane"><div class="lb">runs · 7 today · $17.11</div><div class="rows">${RUNS.map((r, i) => { const c = C[r[0]];
      return `<button class="row r5${i === S.sel.runs ? ' sel' : ''}" data-a="rsel:${i}"><span class="tag ${c.tc}">${c.tag}</span><span class="t mono">${c.skill}</span><span class="t">${esc(c.t)}</span><span class="w mono">${r[1]}</span><span class="w mono">${r[2]}</span></button>`; }).join('')}</div></div>`;
  }
  function vReleases() {
    const st = [['Cut', 'release-pr · PR #1036'], ['Grind', 'pr-grind · approved r3'], ['Merge', 'you · 20m ago'], ['Notify', 'release-note · #dc-supports']];
    const n = C['rel-1036'];
    const relDone = !n.need;
    return `<div class="hd"><span class="mu">wasensi-backend · staging → master</span><span class="grow"></span>
      <button class="btn" data-a="rk:c"><kbd>c</kbd>Cut release</button><button class="btn" data-a="rk:g"><kbd>g</kbd>Grind</button><button class="btn" data-a="rk:n"><kbd>n</kbd>Notify</button></div>
      <div class="steps">${st.map((x, i) => { const done = i < 3 || relDone; const now = i === 3 && !relDone;
        return `<div class="step${done ? ' done' : ''}${now ? ' now' : ''}"><b>${done ? '[✓]' : now ? '[▸]' : '[ ]'} ${x[0]}</b><span>${x[1]}</span></div>`; }).join('')}</div>
      <div class="grid2"><div class="pane"><div class="lb">release note preview</div><div class="det"><pre class="note">${esc(n.note)}</pre>
      ${relDone ? '<span class="c-o">Posted. Never retried.</span>' : '<div class="acts"><button class="btn pri" data-a="rk:p"><kbd>p</kbd>Post to #dc-supports</button><button class="btn" data-a="rk:e"><kbd>e</kbd>Edit</button></div>'}</div></div>
      <div class="pane"><div class="lb">other repos</div><div class="kv"><span>wasensi-web</span><span>6 PRs waiting</span><span>bop-bd</span><span>released 3 Nov</span><span>bop-bd-ui</span><span>nothing new</span><span>release #1040</span><span class="c-q">grinding · round 3</span></div></div></div>`;
  }
  function vOps() {
    return `<div class="pane"><div class="lb">ops</div><div class="rows">${OPS.map((o, i) =>
      `<button class="row${i === S.sel.ops ? ' sel' : ''}" data-a="osel:${i}" style="grid-template-columns:minmax(0,1.1fr) 90px minmax(0,1.4fr)"><span class="t mono">${o[0]}</span><span class="w">${o[1]}</span><span class="t mu">${o[2]}</span></button>`).join('')}</div></div>`;
  }
  function vMe() {
    return `<div class="grid2"><div class="pane"><div class="lb">day end</div><div class="det"><span class="mu">Today isn't reconciled. 2 days this month are missing.</span><div class="acts"><button class="btn pri" data-a="toast:Started blubird:day-end-reconcile (dry run first)"><kbd>r</kbd>Reconcile today</button></div></div></div>
      <div class="pane"><div class="lb">weekly review</div><div class="det"><span class="mu">Week 46 not drafted.</span><div class="acts"><button class="btn" data-a="toast:Started blubird:weekly-review"><kbd>w</kbd>Draft week 46</button></div></div></div>
      <div class="pane"><div class="lb">usage</div><div class="det"><span>work · Max · 5h 62% · week 41%</span><div class="meter"><i style="width:62%"></i></div><span>personal · Pro · 5h 8%</span><div class="meter"><i style="width:8%"></i></div><span class="dim">$212 this month · 148 sessions</span></div></div></div>`;
  }
  function vSettings() {
    return `<div class="grid2">${vAppearance()}<div class="pane"><div class="lb">blubird</div><div class="det"><div class="kv"><span>installed</span><span class="c-o">0.26.3</span><span>latest</span><span>0.26.3 · up to date</span><span>marketplace</span><span class="mono">agentic-workflow</span><span>hooks</span><span>guard · secret masking · idle guard</span></div>
      <div class="acts"><button class="btn" data-a="toast:blubird 0.26.3 is the latest"><kbd>u</kbd>Check / update</button><button class="btn" data-a="toast:Reinstalling blubird"><kbd>i</kbd>Reinstall</button></div></div></div>
      <div class="pane"><div class="lb">release note</div><div class="kv"><span>channel</span><span>#dc-supports</span><span>cc</span><span>Ashique, Najmul, Abir</span><span>suffix</span><span>vai</span></div></div>
      <div class="pane"><div class="lb">products</div><div class="kv"><span>Wasensi</span><span>wasensi-docs + backend, web</span><span>BOP BD</span><span>bop-bd + bop-bd-ui</span><span>Deshi Commerce</span><span>wiki + dc-backend, store-front</span></div></div>
      <div class="pane"><div class="lb">more</div><div class="kv"><span>accounts</span><span>work (Max) · personal (Pro)</span><span>away mode</span><span>off</span><span>notifications</span><span>macOS + phone push</span><span>peer review</span><span>4 lenses</span><span>jev · vault</span><span>connected</span></div></div></div>`;
  }
  function vDetail(id) {
    const c = C[id]; if (!c) return '<div class="empty">Select something.</div>';
    return `<div class="det"><div class="dh"><span class="tag ${c.tc}">${c.tag}</span><b>${esc(c.t)}</b>${S.layout === 'drawer' ? '<button class="btn" data-a="close"><kbd>esc</kbd>close</button>' : ''}</div>
      <span class="dim mono">${c.skill} · ${c.repo}</span>
      ${c.log ? `<div class="log">${c.log.map((l) => `<span>${esc(l)}</span>`).join('')}</div>` : ''}
      ${c.ask && c.need ? `<div class="ask"><b>${esc(c.ask.q)}</b>${c.ask.o.map((o, i) => `<button class="btn${i ? '' : ' pri'}" data-a="ans:${id}:${i}"><kbd>${'abc'[i]}</kbd>${esc(o)}</button>`).join('')}</div>` : ''}
      ${c.note && c.need ? `<pre class="note">${esc(c.note)}</pre>` : ''}
      <div class="acts">${(c.acts || []).map((a, i) => `<button class="btn" data-a="act:${id}:${i}"><kbd>${a[0]}</kbd>${a[1]}</button>`).join('')}</div></div>`;
  }
  const VIEWS = { river: vRiver, inbox: vInbox, runs: vRuns, releases: vReleases, ops: vOps, me: vMe, settings: vSettings };
  const HINTS = {
    river: [['h/l', 'stage'], ['j/k', 'card'], ['⏎', 'open'], ['a/b/c', 'answer']],
    inbox: [['j/k', 'move'], ['⏎', 'open'], ['a/b/c', 'answer']],
    runs: [['j/k', 'move'], ['⏎', 'open']],
    releases: [['c', 'cut'], ['g', 'grind'], ['n', 'note'], ['p', 'post']],
    ops: [['j/k', 'move'], ['⏎', 'run']], me: [['r', 'reconcile'], ['w', 'weekly']], settings: [['u', 'update'], ['i', 'reinstall']],
  };

  function navItems(cls) {
    return SCREENS.map((s, i) => { const n = s[0] === 'inbox' ? inboxIds().length : 0;
      return `<button class="nv${S.screen === s[0] ? ' on' : ''}" data-a="go:${s[0]}"><kbd>${i + 1}</kbd>${s[1]}${n ? `<span class="n">${n}</span>` : ''}</button>`; }).join('');
  }
  function palette() {
    const q = S.palQ.toLowerCase(); const list = SKILLS.filter((s) => s[0].includes(q));
    S.palList = list; S.palI = clamp(S.palI, 0, Math.max(0, list.length - 1));
    return `<div class="ov" data-a="palclose"><div class="dlg" data-a="noop"><input id="palq" placeholder="Run a skill…" value="${esc(S.palQ)}" aria-label="Search skills">${list.map((s, i) =>
      `<button class="pi${i === S.palI ? ' sel' : ''}" data-a="run:${i}"><span class="c-w">/</span>${s[0]}<span class="r">${s[1]}</span></button>`).join('')}</div></div>`;
  }
  function help() {
    const all = [['1-7', 'switch screen'], [': or ⌘K', 'run a skill'], ['⏎', 'open selected'], ['esc', 'close'], ['a/b/c', 'answer a question'], ['.', 'theme: system / dark / light']]
      .concat([['s', 'look: console / river'], ['L', 'layout: drawer / split']]).concat([['?', 'this help']]);
    return `<div class="ov" data-a="helpclose"><div class="dlg" data-a="noop"><div class="help">${all.map((k) => `<kbd>${k[0]}</kbd><span>${k[1]}</span>`).join('')}</div></div></div>`;
  }

  function render() {
    if (S.theme === 'system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', S.theme);
    document.body.className = 'skin-' + S.skin;
    const title = SCREENS.find((s) => s[0] === S.screen)[1];
    const prods = S.screen === 'river' ? PRODUCTS.map((p, i) => `<button class="prod${i === S.product ? ' on' : ''}" data-a="prod:${i}">${p}</button>`).join('') : '';
    const head = `<div class="hd"><h1>${title.toLowerCase()}</h1>${prods}<span class="grow"></span><button class="btn" data-a="pal"><kbd>:</kbd>run skill</button></div>`;
    const keys = `<footer class="keys">${HINTS[S.screen].concat([['1-7', 'screens'], [':', 'skill'], ['.', 'theme']]).concat(true ? [['s', 'skin: ' + S.skin]] : []).concat([['?', 'keys']])
      .map((h) => `<span><kbd>${h[0]}</kbd>${h[1]}</span>`).join('')}</footer>`;
    const showSide = S.layout === 'split' && ['river', 'inbox', 'runs'].includes(S.screen);
    let html;
    if (S.layout === 'split') {
      html = `<div class="app"><header class="tabs"><div class="brand"><b>setu</b><span>সেতু</span></div>${navItems()}<span class="st">blubird 0.26.3 · work 62% · away off</span></header>
        <div class="body"><main class="main">${head}${VIEWS[S.screen]()}</main>${showSide ? `<aside class="side" aria-label="Detail">${vDetail(cur())}</aside>` : ''}</div>${keys}</div>`;
    } else {
      html = `<div class="app"><div class="body"><nav class="rail" aria-label="Main"><div class="brand"><b>setu</b><span>সেতু</span></div>${navItems()}
        <div class="railfoot"><span>blubird 0.26.3</span><span>work · 62%</span><span>away off</span></div></nav>
        <main class="main">${head}${VIEWS[S.screen]()}</main></div>${keys}${S.open ? `<aside class="drawer" aria-label="Detail">${vDetail(S.open)}</aside>` : ''}</div>`;
    }
    html += (S.pal ? palette() : '') + (S.help ? help() : '') + (S.toast ? `<div class="toast" role="status">${esc(S.toast)}</div>` : '');
    document.getElementById('root').innerHTML = html;
    if (S.pal) { const i = document.getElementById('palq'); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
  }

  // ---------- input ----------
  function runPal(i) { const s = (S.palList || [])[i]; S.pal = false; S.palQ = ''; if (s) toast('Pick a target, then setu starts ' + s[0] + ' in the right repo'); render(); }
  function releaseKey(k) {
    const n = C['rel-1036'];
    if (k === 'c') toast('Started release-pr in wasensi-backend');
    else if (k === 'g') toast('Started pr-grind on the release PR');
    else if (k === 'n') toast('Note preview is below');
    else if (k === 'p' && n.need) { n.need = false; n.tag = 'done'; n.tc = 'c-o'; toast('Posted once to #dc-supports'); }
    else if (k === 'e') toast('Editing the note');
    else return false;
    render(); return true;
  }
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-a]'); if (!el) return;
    const [a, x, y] = el.dataset.a.split(':');
    if (a === 'noop') return;
    if (a === 'go') go(x);
    else if (a === 'card') { S.st = +x; S.ci = +y; if (S.layout === 'drawer') S.open = cur(); render(); }
    else if (a === 'isel') { S.sel.inbox = +x; if (S.layout === 'drawer') S.open = cur(); render(); }
    else if (a === 'rsel') { S.sel.runs = +x; if (S.layout === 'drawer') S.open = cur(); render(); }
    else if (a === 'osel') { S.sel.ops = +x; toast('Started ' + OPS[+x][0]); render(); }
    else if (a === 'ans') answer(x, +y);
    else if (a === 'act') act(x, +y);
    else if (a === 'close') { S.open = null; render(); }
    else if (a === 'pal') { S.pal = true; render(); }
    else if (a === 'palclose') { if (e.target === el) { S.pal = false; render(); } }
    else if (a === 'helpclose') { if (e.target === el) { S.help = false; render(); } }
    else if (a === 'run') runPal(+x);
    else if (a === 'prod') { S.product = +x; render(); }
    else if (a === 'rk') releaseKey(x);
    else if (a === 'pref') { S[x] = y; S.open = null; savePrefs(); render(); }
    else if (a === 'toast') { toast(el.dataset.a.slice(6)); render(); }
  });
  document.addEventListener('input', (e) => { if (e.target.id === 'palq') { S.palQ = e.target.value; S.palI = 0; render(); } });
  addEventListener('keydown', (e) => {
    const k = e.key;
    if (S.pal) {
      if (k === 'Escape') { S.pal = false; render(); }
      else if (k === 'ArrowDown') { S.palI++; render(); e.preventDefault(); }
      else if (k === 'ArrowUp') { S.palI--; render(); e.preventDefault(); }
      else if (k === 'Enter') runPal(S.palI);
      return;
    }
    if ((e.metaKey || e.ctrlKey) && k === 'k') { e.preventDefault(); S.pal = true; render(); return; }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (k === ':') { e.preventDefault(); S.pal = true; render(); return; }
    if (k === '?') { S.help = !S.help; render(); return; }
    if (k === 'Escape') { S.open = null; S.help = false; render(); return; }
    if (k === '.') { S.theme = { system: 'dark', dark: 'light', light: 'system' }[S.theme]; savePrefs(); toast('Mode: ' + S.theme); render(); return; }
    if (k === 's') { S.skin = S.skin === 'console' ? 'river' : 'console'; savePrefs(); toast('Look: ' + S.skin); render(); return; }
    if (k === 'L') { S.layout = S.layout === 'drawer' ? 'split' : 'drawer'; S.open = null; savePrefs(); toast('Layout: ' + S.layout); render(); return; }
    if (/^[1-7]$/.test(k)) { go(SCREENS[+k - 1][0]); return; }
    const t = target();
    if (t && C[t]) {
      const c = C[t];
      const ai = 'abc'.indexOf(k);
      if (c.need && c.ask && ai >= 0 && ai < c.ask.o.length) { answer(t, ai); return; }
      const xi = (c.acts || []).findIndex((a) => a[0] === k);
      if (xi >= 0) { act(t, xi); return; }
    }
    if (S.screen === 'river') {
      if (k === 'h' || k === 'ArrowLeft') { S.st = clamp(S.st - 1, 0, STAGES.length - 1); S.ci = clamp(S.ci, 0, STAGES[S.st].cards.length - 1); }
      else if (k === 'l' || k === 'ArrowRight') { S.st = clamp(S.st + 1, 0, STAGES.length - 1); S.ci = clamp(S.ci, 0, STAGES[S.st].cards.length - 1); }
      else if (k === 'j' || k === 'ArrowDown') S.ci = clamp(S.ci + 1, 0, STAGES[S.st].cards.length - 1);
      else if (k === 'k' || k === 'ArrowUp') S.ci = clamp(S.ci - 1, 0, STAGES[S.st].cards.length - 1);
      else if (k === 'Enter') S.open = cur();
      else return;
      if (S.open && k !== 'Enter') S.open = cur();
      e.preventDefault(); render(); return;
    }
    if (S.screen === 'inbox' || S.screen === 'runs' || S.screen === 'ops') {
      const len = S.screen === 'inbox' ? inboxIds().length : S.screen === 'runs' ? RUNS.length : OPS.length;
      const key = S.screen;
      if (k === 'j' || k === 'ArrowDown') S.sel[key] = clamp(S.sel[key] + 1, 0, len - 1);
      else if (k === 'k' || k === 'ArrowUp') S.sel[key] = clamp(S.sel[key] - 1, 0, len - 1);
      else if (k === 'Enter') { if (key === 'ops') toast('Started ' + OPS[S.sel.ops][0]); else S.open = cur(); }
      else return;
      if (S.open && k !== 'Enter' && key !== 'ops') S.open = cur();
      e.preventDefault(); render(); return;
    }
    if (S.screen === 'releases') { releaseKey(k); return; }
    if (S.screen === 'me') { if (k === 'r') { toast('Started blubird:day-end-reconcile (dry run first)'); render(); } if (k === 'w') { toast('Started blubird:weekly-review'); render(); } return; }
    if (S.screen === 'settings') { if (k === 'u') { toast('blubird 0.26.3 is the latest'); render(); } if (k === 'i') { toast('Reinstalling blubird'); render(); } }
  });
  // inbox keeps its selection valid after items clear
  const _render = render;
  render = function () { S.sel.inbox = clamp(S.sel.inbox, 0, Math.max(0, inboxIds().length - 1)); _render(); };
  render();
})();
