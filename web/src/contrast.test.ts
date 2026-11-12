import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const lum = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!;
};
const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x! + 0.05) / (y! + 0.05); };
function tokens(selector: string): Record<string, string> {
  const re = new RegExp(`${selector.replace(/[.[\]"=]/g, "\\$&")}\\s*\\{([^}]*)\\}`);
  const m = re.exec(css);
  expect(m, selector).not.toBeNull();
  return Object.fromEntries([...m![1]!.matchAll(/--(\w+):(#[0-9A-Fa-f]{6})/g)].map((x) => [x[1]!, x[2]!]));
}
const combos: [string, string][] = [
  ["console dark", "body.skin-console"], ["river dark", "body.skin-river"],
  ["console light", 'html[data-theme="light"] body.skin-console'], ["river light", 'html[data-theme="light"] body.skin-river'],
];
describe("WCAG AA contrast in all four look x mode combinations", () => {
  for (const [name, sel] of combos) {
    it(name, () => {
      const t = tokens(sel);
      for (const surface of ["bg", "p1", "p2"]) {
        for (const fg of ["tx", "mu", "dim", "acc", "q", "bad", "ok", "warn"]) {
          expect(ratio(t[fg]!, t[surface]!), `${fg} on ${surface}`).toBeGreaterThanOrEqual(4.5);
        }
      }
      expect(ratio(t.accink!, t.acc!), "accink on acc").toBeGreaterThanOrEqual(4.5);
      expect(ratio(t.tx!, t.sel!), "tx on sel").toBeGreaterThanOrEqual(4.5);
      expect(ratio(t.mu!, t.sel!), "mu on sel").toBeGreaterThanOrEqual(4.5);
    });
  }
});
