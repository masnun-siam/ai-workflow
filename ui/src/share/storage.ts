// The reviewer's display name, remembered per browser. Private mode can make localStorage throw.
const KEY = 'aiw-share-name';
let memory = '';

export function getName(): string {
  try { return localStorage.getItem(KEY) ?? ''; } catch { return memory; }
}

export function setName(n: string): void {
  memory = n;
  try { localStorage.setItem(KEY, n); } catch { /* kept in memory */ }
}
