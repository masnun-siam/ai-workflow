// Record crisp tour clips of the isolated aiw ui (port 8431): PNG frames captured in a loop while a
// scripted, eased cursor drives the page, then stitched by ffmpeg with each frame's real duration.
// usage: PW=<dir with node_modules/playwright-core> node site/scripts/tour.mjs board|session|inbox|dispatch [session_id]
import { createRequire } from 'node:module';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const { chromium } = createRequire(process.env.PW + '/')('playwright-core');
const [clip, sessionId] = process.argv.slice(2);
const UI = 'http://127.0.0.1:8431/#';
const REPO = '?repo=masnun-siam/todoman';
const FEATURE = 'Todoman: dump anything, get GitHub issues and meetings';
const dir = `site/raw/frames-${clip}`;
rmSync(dir, { recursive: true, force: true });
mkdirSync(dir, { recursive: true });

const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, colorScheme: 'dark' });

// a visible cursor, since headless screenshots have none
const CURSOR = `(() => { if (document.getElementById('__c')) return;
  const c = document.createElement('div'); c.id = '__c';
  c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;transition:transform .12s;' +
    'background:url("data:image/svg+xml,' + encodeURIComponent('<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 22 22\\'><path d=\\'M3 2l15 9-7 1.5L7.5 19z\\' fill=\\'white\\' stroke=\\'black\\' stroke-width=\\'1.3\\'/></svg>') + '") no-repeat';
  document.documentElement.appendChild(c);
  addEventListener('mousemove', e => { c.style.left = e.clientX - 3 + 'px'; c.style.top = e.clientY - 2 + 'px'; }, true);
  addEventListener('mousedown', () => c.style.transform = 'scale(.8)', true);
  addEventListener('mouseup', () => c.style.transform = '', true);
})()`;
await page.addInitScript(CURSOR);

let mouse = { x: 800, y: 500 };
const frames = [];
let recording = true;
const loop = (async () => {
  let i = 0;
  while (recording) {
    const t = Date.now();
    const f = `${dir}/${String(i++).padStart(5, '0')}.png`;
    await page.screenshot({ path: f }).catch(() => {});
    frames.push({ f, t });
  }
})();

const wait = (ms) => page.waitForTimeout(ms);
async function moveTo(locator) {
  const b = await locator.first().boundingBox();
  const to = { x: b.x + Math.min(b.width / 2, 60), y: b.y + b.height / 2 };
  const steps = 28;
  for (let s = 1; s <= steps; s++) {
    const k = s / steps, e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2; // ease in-out
    await page.mouse.move(mouse.x + (to.x - mouse.x) * e, mouse.y + (to.y - mouse.y) * e);
    await wait(14);
  }
  mouse = to;
}
async function click(locator, pause = 1200) { await moveTo(locator); await wait(250); await page.mouse.down(); await wait(90); await page.mouse.up(); await wait(pause); }
async function scroll(dy, pause = 900) { for (let i = 0; i < 20; i++) { await page.mouse.wheel(0, dy / 20); await wait(16); } await wait(pause); }

async function open(path) { await page.goto(UI + path); await page.evaluate(CURSOR); await page.mouse.move(mouse.x, mouse.y); await wait(2500); }

if (clip === 'board') {
  await open('/features' + REPO);
  await click(page.getByRole('link', { name: FEATURE }), 2200);
  await scroll(380, 1200);
  await click(page.getByRole('button', { name: /result card: table of created items/ }), 4800);
  await page.keyboard.press('Escape'); await wait(700);
  await scroll(-380, 500);
  await click(page.getByRole('tab', { name: 'PRD' }), 1800);
  await scroll(700, 1800);
} else if (clip === 'session') {
  await open('/sessions/' + sessionId);
  await scroll(700, 1200);
  await scroll(900, 1200);
  await scroll(2400, 2500);
} else if (clip === 'inbox') {
  await open('/inbox');
  await moveTo(page.getByRole('button', { name: 'Review and merge' })); await wait(1800);
  await click(page.getByRole('link', { name: /^Activity/ }), 2600);
  await click(page.getByRole('link', { name: /^Features/ }), 2200);
  await click(page.getByRole('link', { name: /^Inbox/ }), 1800);
} else if (clip === 'dispatch') {
  await open('/features/dump-to-issues' + REPO);
  await click(page.getByRole('button', { name: 'Run epic' }).first(), 1600);
  await click(page.getByText('Simple', { exact: true }), 700);
  await click(page.getByText('Full', { exact: true }), 900);
  await click(page.getByRole('button', { name: 'Preview' }), 7000);
  await scroll(400, 2200);
}

recording = false;
await loop;
await browser.close();

// ffconcat with each frame's real on-screen time, so motion plays at true speed
const lines = ['ffconcat version 1.0'];
frames.forEach(({ f, t }, i) => {
  const next = frames[i + 1]?.t ?? t + 100;
  lines.push(`file '${f.split('/').pop()}'`, `duration ${((next - t) / 1000).toFixed(3)}`);
});
writeFileSync(`${dir}/list.txt`, lines.join('\n') + '\n');
mkdirSync('site/raw/clips', { recursive: true });
execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'concat', '-i', `${dir}/list.txt`, '-vf', 'fps=30,format=yuv420p',
  '-c:v', 'libx264', '-crf', '18', `site/raw/clips/tour-${clip}.mp4`]);
console.log(`tour-${clip}: ${frames.length} frames, ${((frames.at(-1).t - frames[0].t) / 1000).toFixed(1)} s`);
