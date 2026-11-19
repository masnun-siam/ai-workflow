import type { ComponentChildren } from "preact";
import type { Product } from "../api/types";
import { chooseProduct, product, products } from "../state/data";
import { RepoScope } from "./Shell";

export function ProductSwitch() {
  const list = products.value ?? [];
  if (list.length < 2) return null;
  return (
    <div class="chips" role="group" aria-label="Product">
      {list.map((p) => (
        <button key={p.docs_repo} type="button" class={`prod${p.docs_repo === product.value ? " on" : ""}`} aria-pressed={p.docs_repo === product.value} onClick={() => chooseProduct(p.docs_repo)}>{p.name}</button>
      ))}
    </div>
  );
}

/** FR-13: setu wrote the product's map but no commit carries it yet. An older server sends no flag: no note. */
export function MapNote({ p }: { p: Product | undefined }) {
  if (p?.map_committed !== false) return null;
  return <span class="tag c-w" title="The first session's commit should carry .blubird/repos.json.">Map not committed</span>;
}

/** A page heading. `scope` adds the page's repo filter (`?only=`), `products` the product chips (2+ products). */
export function Header({ title, products: withProducts, scope, sub, children }: { title: string; products?: boolean; scope?: boolean; sub?: ComponentChildren; children?: ComponentChildren }) {
  return (
    <div class="hd">
      <div class="hd-t"><h1>{title}</h1>{sub && <span class="mu hd-sub">{sub}</span>}</div>
      {withProducts && <ProductSwitch />}
      {withProducts && <MapNote p={products.value?.find((p) => p.docs_repo === product.value)} />}
      <span class="grow" />
      {children}
      {scope && <RepoScope />}
    </div>
  );
}
