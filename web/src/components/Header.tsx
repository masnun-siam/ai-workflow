import type { ComponentChildren } from "preact";
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

/** A page heading. `scope` adds the page's repo filter (`?only=`), `products` the product chips (2+ products). */
export function Header({ title, products: withProducts, scope, sub, children }: { title: string; products?: boolean; scope?: boolean; sub?: ComponentChildren; children?: ComponentChildren }) {
  return (
    <div class="hd">
      <div class="hd-t"><h1>{title}</h1>{sub && <span class="mu hd-sub">{sub}</span>}</div>
      {withProducts && <ProductSwitch />}
      <span class="grow" />
      {children}
      {scope && <RepoScope />}
    </div>
  );
}
