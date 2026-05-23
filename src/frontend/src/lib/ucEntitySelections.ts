import { api } from "@/lib/api-client";

export interface UcEntitySelection {
  table_full_name: string;
  column_name: string;
  catalog?: string;
  schema?: string;
  table_name?: string;
  type_text?: string;
  comment?: string;
}

export function entityKey(tableFullName: string, columnName: string): string {
  return `${tableFullName}#${columnName}`;
}

export async function loadUcEntitySelections(): Promise<UcEntitySelection[]> {
  try {
    const res = await api.get<{ entities: UcEntitySelection[] }>(
      "/api/v1/uc/entity-selections",
    );
    return res.entities ?? [];
  } catch {
    return [];
  }
}

export async function saveUcEntitySelections(
  entities: UcEntitySelection[],
): Promise<void> {
  await api.put("/api/v1/uc/entity-selections", { entities });
}
