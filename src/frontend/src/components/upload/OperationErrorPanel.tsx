"use client";

interface OperationErrorPanelProps {
  title: string;
  detail: string;
}

/** Upload / import failure with copy-pasteable multiline diagnostics. */
export default function OperationErrorPanel({ title, detail }: OperationErrorPanelProps) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-4">
      <p className="text-red-700 font-medium">{title}</p>
      <pre className="mt-2 text-xs text-red-800 whitespace-pre-wrap break-words font-mono leading-relaxed max-h-64 overflow-y-auto rounded bg-red-100/60 p-3 border border-red-200/80">
        {detail}
      </pre>
    </div>
  );
}
