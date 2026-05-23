"use client";

import Link from "next/link";
import type { ComponentProps } from "react";

type AppLinkProps = Omit<ComponentProps<typeof Link>, "href"> & {
  href: string;
};

/** Client-side navigation (avoids full reload on Databricks static export). */
export default function AppLink({ href, ...props }: AppLinkProps) {
  const path = href.startsWith("/") ? href : `/${href}`;
  return <Link href={path} prefetch={true} {...props} />;
}
