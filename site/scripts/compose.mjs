// Compose the captioned run video (site/raw/run.mp4, 16:10) and the social promo (site/raw/promo.mp4, 4:5)
// from the raw captures. Captions and cards are HTML rendered by Chrome, so they use the site's type.
// usage: PW=<dir with node_modules/playwright-core> node site/scripts/compose.mjs
import { createRequire } from 'node:module';
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const { chromium } = createRequire(process.env.PW + '/')('playwright-core');
const raw = 'site/raw';
const tmp = `${raw}/compose`;
mkdirSync(tmp, { recursive: true });
const ff = (...a) => execFileSync('ffmpeg', ['-loglevel', 'error', '-y', ...a]);
// inlined: a setContent page cannot load file:// fonts
const woff = (w) => 'data:font/woff2;base64,' +
  readFileSync(`site/node_modules/@fontsource/hanken-grotesk/files/hanken-grotesk-latin-${w}-normal.woff2`).toString('base64');
const font = woff(800);
const font4 = woff(400);

// what happened, in order; numbers are from the real run
const segs = [
  { still: 'new-feature-filled.png', cap: 'Type the idea, pick the reviewers', sec: 3.2 },
  { still: 'prd-questions.png', cap: 'Claude reads the code, then asks you 3 questions', sec: 3.6 },
  { lapse: 'tl-prd', cap: 'Critical, CTO and QA lenses review the PRD over 3 rounds', fps: 14 },
  { still: 'refined-issue.png', cap: 'Issue #40 filed and refined: what, why, how', sec: 3.4 },
  { lapse: 'tl-impl', cap: 'Built in its own worktree, 235 tests passing', fps: 9 },
  { still: 'pr-files.png', cap: 'PR #42: 13 files, CI green, reviewed', sec: 3.4 },
];
const END = ['11.5 minutes from idea to a ready pull request', '$2.96 of Claude, 3 decisions by a person'];

const browser = await chromium.launch({ channel: 'chrome' });
async function render(html, w, h, out, transparent) {
  const p = await browser.newPage({ viewport: { width: w, height: h } });
  await p.setContent(`<style>
    @font-face{font-family:H;src:url(${font});font-weight:800}
    @font-face{font-family:H;src:url(${font4});font-weight:400}
    *{margin:0;box-sizing:border-box} body{font-family:H;color:#e8ebf5;${transparent ? 'background:transparent' : 'background:#0a0e1a'}}
  </style>${html}`);
  await p.evaluate(() => document.fonts.ready);
  await p.screenshot({ path: out, omitBackground: transparent });
  await p.close();
}
const caption = (text, n) => `<div style="position:fixed;left:288px;bottom:44px;display:flex;align-items:center;gap:18px;
  padding:16px 26px 16px 18px;border-radius:14px;background:rgba(10,14,26,.92);border:1px solid #232b42;box-shadow:0 20px 50px rgba(0,0,0,.5)">
  <span style="display:grid;place-items:center;width:38px;height:38px;border-radius:50%;background:#8b98ff;color:#0a0e1a;font-weight:800;font-size:20px">${n}</span>
  <span style="font-weight:800;font-size:30px;letter-spacing:-.02em">${text}</span></div>`;
const card = (big, small, w) => `<div style="height:100vh;display:grid;place-content:center;gap:22px;padding:0 ${w / 12}px;
  background:radial-gradient(60% 50% at 50% 55%,rgba(139,152,255,.18),transparent 70%),#0a0e1a">
  <div style="font-weight:800;font-size:${w / 18}px;line-height:1.05;letter-spacing:-.035em">${big}</div>
  <div style="font-size:${w / 46}px;color:#8c94ad">${small}</div></div>`;

// captures differ in height (full-page shots, a short viewport): top 1000 px, padded with the UI's background
const FIT = "scale=1600:-2,crop=1600:'min(ih,1000)':0:0,pad=1600:1000:0:0:color=0x0f1216";
const V = ['-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', '30', '-an'];
// one segment as a 1600x1000 clip: a slow push-in on a still, or the timelapse frames at their pace
function segment(s, i) {
  const out = `${tmp}/seg${i}.mp4`;
  if (s.still) {
    const n = Math.round(s.sec * 30);
    ff('-loop', '1', '-i', `${raw}/${s.still}`, '-i', `${tmp}/cap${i}.png`, '-filter_complex',
      `[0]${FIT},scale=3200:-1,zoompan=z='1+0.06*on/${n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=${n}:s=1600x1000:fps=30[b];[b][1]overlay`,
      '-t', String(s.sec), ...V, out);
  } else {
    ff('-framerate', String(s.fps), '-pattern_type', 'glob', '-i', `${raw}/${s.lapse}/*.png`, '-i', `${tmp}/cap${i}.png`,
      '-filter_complex', `[0]${FIT},setsar=1[b];[b][1]overlay`, ...V, out);
  }
  return out;
}

for (const [i, s] of segs.entries()) await render(caption(s.cap, i + 1), 1600, 1000, `${tmp}/cap${i}.png`, true);
await render(card(END[0], END[1], 1600), 1600, 1000, `${tmp}/end.png`);
const parts = segs.map(segment);
const still = (png, out) => ff('-loop', '1', '-i', `${tmp}/${png}`, '-t', '3', ...V, `${tmp}/${out}`);
const concat = (list, out) => {
  writeFileSync(`${tmp}/list.txt`, list.map((p) => `file '${p.split('/').pop()}'`).join('\n'));
  ff('-f', 'concat', '-safe', '0', '-i', `${tmp}/list.txt`, '-c', 'copy', out);
};
concat(parts, `${tmp}/body.mp4`);
still('end.png', 'end.mp4');
concat([`${tmp}/body.mp4`, `${tmp}/end.mp4`], `${raw}/run.mp4`);

// promo, 1080x1350: intro card, the run with the UI's 240 px sidebar cropped so it reads on a phone, end and outro cards
await render(card('Type an idea.<br>Get back a reviewed pull request.', 'A real run of ai-workflow on Claude Code', 1080), 1080, 1350, `${tmp}/p-intro.png`);
await render(card(END[0], END[1], 1080), 1080, 1350, `${tmp}/p-end.png`);
await render(card('ai-workflow', 'github.com/masnun-siam/ai-workflow', 1080), 1080, 1350, `${tmp}/p-outro.png`);
still('p-intro.png', 'p-intro.mp4');
still('p-end.png', 'p-end.mp4');
still('p-outro.png', 'p-outro.mp4');
ff('-i', `${tmp}/body.mp4`, '-vf', 'crop=1360:1000:240:0,scale=1080:-2,pad=1080:1350:0:(oh-ih)/2:color=0x0a0e1a', ...V, `${tmp}/p-body.mp4`);
concat(['p-intro', 'p-body', 'p-end', 'p-outro'].map((f) => `${tmp}/${f}.mp4`), `${raw}/promo.mp4`);

await browser.close();
console.log(readdirSync(tmp).length, 'files in', tmp);
