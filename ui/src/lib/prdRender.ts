// mermaid is ~1MB, so it is only fetched when a PRD actually has a diagram.
export async function renderDiagrams(root: HTMLElement | null) {
  const nodes = root ? Array.from(root.querySelectorAll<HTMLElement>('pre.mermaid')) : [];
  if (!nodes.length) return;
  const { default: mermaid } = await import('mermaid');
  const dark = getComputedStyle(document.documentElement).colorScheme === 'dark';
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: dark ? 'dark' : 'default' });
  await mermaid.run({ nodes, suppressErrors: true });
}

// A wide diagram fits the column with tiny labels; a click toggles it to natural size, scrolled sideways.
export function toggleDiagram(e: React.MouseEvent) {
  const svg = (e.target as Element).closest('pre.mermaid')?.querySelector('svg');
  if (!svg) return;
  const full = !svg.style.width;
  svg.style.width = full ? `${svg.viewBox.baseVal.width}px` : '';
  svg.style.maxWidth = full ? 'none' : `${svg.viewBox.baseVal.width}px`;
  svg.parentElement!.classList.toggle('full', full);
}

// The PRD text without its leading title line; both PRD surfaces render this.
export const prdBody = (text: string): string => text.replace(/^\s*# [^\n]*\n/, '');
