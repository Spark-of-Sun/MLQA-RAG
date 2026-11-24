import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ProductDetail } from "@/components/site/product-detail";
import { getProduct } from "@/components/site/products";
import { pageMeta } from "@/components/site/seo";

const product = getProduct("legal");

export const metadata: Metadata = product ? pageMeta(product.fullName, product.intro, "/products/legal") : {};

export default function LegalProductPage() {
  if (!product) notFound();
  return <ProductDetail product={product} />;
}
