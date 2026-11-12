import type { ComponentChildren } from "preact";
import { chooseProduct, product, products } from "../state/data";
import { paletteOpen } from "../state/ui";
import { Btn } from "./ui";

export function ProductSwitch() {
  const list = products.value ?? [];
  if (list.length < 2) return null;
  return (
    <div class="chips" role="group" aria-label="Product">
      {list.map((p) => (
        <button type="button" class={`prod${p.docs_repo === product.value ? " on" : ""}`} aria-pressed={p.docs_repo === product.value} onClick={() => chooseProduct(p.docs_repo)}>{p.name}</button>
      ))}
    </div>
  );
}

export function Header({ title, products: withProducts, children }: { title: string; products?: boolean; children?: ComponentChildren }) {
  return (
    <div class="hd">
      <h1>{title}</h1>
      {withProducts && <ProductSwitch />}
      <span class="grow" />
      {children}
      <Btn k=":" onClick={() => (paletteOpen.value = true)}>run skill</Btn>
    </div>
  );
}
