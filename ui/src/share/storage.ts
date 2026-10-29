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

// This browser's approval of one share: the name and the withdraw key the server returned once.
export interface StoredApproval { name: string; key: string }
const approvalKey = (token: string) => `aiw-share-approval:${token}`;
const approvals: Record<string, StoredApproval> = {};

export function getApproval(token: string): StoredApproval | null {
  try {
    const v = JSON.parse(localStorage.getItem(approvalKey(token)) ?? 'null');
    return typeof v?.name === 'string' && typeof v?.key === 'string' ? v : null;
  } catch { return approvals[token] ?? null; }
}

export function setApproval(token: string, name: string, key: string): void {
  approvals[token] = { name, key };
  try { localStorage.setItem(approvalKey(token), JSON.stringify({ name, key })); } catch { /* kept in memory */ }
}

export function clearApproval(token: string): void {
  delete approvals[token];
  try { localStorage.removeItem(approvalKey(token)); } catch { /* memory already cleared */ }
}
