import { redirect } from "next/navigation";

/** Legacy `/workspace` → graph canvas at `/dashboard`. */
export default async function WorkspaceRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(sp)) {
    if (typeof value === "string") {
      qs.set(key, value);
    } else if (Array.isArray(value)) {
      value.forEach((v) => qs.append(key, v));
    }
  }
  const query = qs.toString();
  redirect(query ? `/dashboard?${query}` : "/dashboard");
}
