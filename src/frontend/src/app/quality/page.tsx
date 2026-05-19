import { redirect } from "next/navigation";

export default function QualityPage() {
  redirect("/ontology-quality?tab=per-ontology-quality");
}
