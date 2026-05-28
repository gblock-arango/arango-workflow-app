/**
 * Schedule work after the browser has painted so navigation feels instant.
 * Uses double requestAnimationFrame (after layout/paint) plus optional delay.
 */
export function scheduleAfterInitialPaint(
  fn: () => void,
  delayMs = 0,
): () => void {
  let cancelled = false;
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  const run = () => {
    if (cancelled) return;
    if (delayMs <= 0) {
      fn();
    } else {
      timeoutId = setTimeout(() => {
        if (!cancelled) fn();
      }, delayMs);
    }
  };

  const frameId = requestAnimationFrame(() => {
    requestAnimationFrame(run);
  });

  return () => {
    cancelled = true;
    cancelAnimationFrame(frameId);
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  };
}
