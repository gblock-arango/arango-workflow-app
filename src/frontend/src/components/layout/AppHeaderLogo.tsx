"use client";

import Image from "next/image";
import { withBasePath } from "@/lib/base-path";

/** Arango wordmark — upper-right placement on app headers (matches home page). */
export default function AppHeaderLogo() {
  return (
    <Image
      src={withBasePath("/images/arango-logo-transparent.png")}
      alt="Arango"
      width={200}
      height={56}
      className="h-10 sm:h-12 w-auto object-contain"
      priority
    />
  );
}
