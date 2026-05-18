/** Shared confidence/quality score thresholds and their display colors. */

export const CONFIDENCE_HIGH = 0.7;
export const CONFIDENCE_MEDIUM = 0.5;

/** Return a Tailwind text-color class for a 0–1 confidence score. */
export function confidenceColor(score: number): string {
  if (score > CONFIDENCE_HIGH) return "text-green-600";
  if (score >= CONFIDENCE_MEDIUM) return "text-yellow-600";
  return "text-red-600";
}

/** Return a Tailwind bg-color class for a 0–1 confidence score. */
export function confidenceBgColor(score: number): string {
  if (score > CONFIDENCE_HIGH) return "bg-green-100";
  if (score >= CONFIDENCE_MEDIUM) return "bg-yellow-100";
  return "bg-red-100";
}

/** Return a Tailwind text-color class for a 0–100 health/quality score. */
export function healthScoreColor(score: number): string {
  if (score >= 70) return "text-green-600";
  if (score >= 50) return "text-yellow-600";
  return "text-red-600";
}
