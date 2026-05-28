/** Parse SQL/UC boolean values (``bool('false')`` in Python is true — same pitfall in JS for loose checks). */
export function sqlBool(value: unknown): boolean {
  if (value === true || value === 1) return true;
  if (value === false || value === 0 || value == null) return false;
  if (typeof value === "string") {
    const s = value.trim().toLowerCase();
    if (s === "false" || s === "0" || s === "no" || s === "off" || s === "") return false;
    if (s === "true" || s === "1" || s === "yes" || s === "t") return true;
  }
  return Boolean(value);
}
