import { useCallback, useRef, useState } from "react";
import { t } from "../i18n/strings";

const MAX_BYTES = 20 * 1024 * 1024;
const ACCEPTED_EXTS = ".pdf,.txt,.csv,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff";

interface Props {
  loading: boolean;
  onSubmit: (file: File) => void;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export function InvoiceUpload({ loading, onSubmit }: Props) {
  const s = t().upload;
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const setIfValid = useCallback(
    (f: File | null) => {
      setError(null);
      if (!f) {
        setFile(null);
        return;
      }
      if (f.size > MAX_BYTES) {
        setError(s.formats + ` (${formatBytes(f.size)})`);
        setFile(null);
        return;
      }
      setFile(f);
    },
    [s.formats],
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files?.[0] ?? null;
      setIfValid(f);
    },
    [setIfValid],
  );

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        className={[
          "flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed bg-white px-8 py-12 text-center transition-colors",
          dragOver ? "border-blue-400 bg-blue-50 dropzone-active" : "border-slate-300",
          "hover:border-blue-400 cursor-pointer",
        ].join(" ")}
      >
        <svg
          className="h-10 w-10 text-slate-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 7.5m0 0L7.5 12M12 7.5v9"
          />
        </svg>
        <p className="text-base font-medium text-slate-700">{s.dropHere}</p>
        <p className="text-sm text-slate-500">{s.orClick}</p>
        <p className="text-xs text-slate-400">
          {s.formats} · {s.maxSize}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTS}
          className="hidden"
          onChange={(e) => setIfValid(e.target.files?.[0] ?? null)}
        />
      </div>

      {file && (
        <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3">
          <div className="truncate">
            <div className="text-xs uppercase tracking-wide text-slate-400">
              {s.selected}
            </div>
            <div className="truncate text-sm font-medium text-slate-800">
              {file.name}{" "}
              <span className="text-slate-400">({formatBytes(file.size)})</span>
            </div>
          </div>
          <button
            type="button"
            className="text-sm text-blue-600 hover:underline"
            onClick={() => inputRef.current?.click()}
          >
            {s.change}
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <button
        type="button"
        disabled={!file || loading}
        onClick={() => file && onSubmit(file)}
        className={[
          "w-full rounded-xl px-4 py-3 text-base font-medium text-white shadow-sm transition-colors",
          !file || loading
            ? "bg-slate-300 cursor-not-allowed"
            : "bg-blue-600 hover:bg-blue-700",
        ].join(" ")}
      >
        {loading ? s.submitting : s.submit}
      </button>
    </div>
  );
}
