export function fmtDur(s: number | null | undefined): string {
  if (s == null) return "";
  const n = Math.max(0, Math.round(s));
  if (n < 60) return `${n}s`;
  const m = Math.floor(n / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h${String(m % 60).padStart(2, "0")}`;
}
export function fmtCost(c: number | null | undefined): string {
  return c == null ? "" : `$${c.toFixed(2)}`;
}
export function ago(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const d = Math.round((now - t) / 1000);
  if (d < 0) return `in ${fmtDur(-d)}`;
  if (d < 45) return "just now";
  return `${fmtDur(d)} ago`;
}
export const shortRepo = (slug: string | null | undefined): string => (slug ? (slug.split("/")[1] ?? slug) : "");
export const epochToIso = (e: number): string => new Date(e * 1000).toISOString();
export const issueUrl = (l: { owner: string; repo: string; issue: number }): string =>
  `https://github.com/${l.owner}/${l.repo}/issues/${l.issue}`;
export const pct = (m: { pct: number } | null | undefined): string => (m ? `${Math.round(m.pct)}%` : "n/a");
export function fmtTokens(t: { input: number; cached: number; output: number } | null): string {
  if (!t) return "";
  const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));
  return `${k(t.input)} in · ${k(t.cached)} cached · ${k(t.output)} out`;
}
