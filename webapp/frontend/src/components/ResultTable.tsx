import { useState } from "react";
import { t } from "../i18n/strings";
import type { ClassificationResult, InvoiceItem } from "../types";
import { DetailPanel } from "./DetailPanel";

interface Props {
  items: InvoiceItem[];
}

interface CodeReview {
  code: string;
  changed: boolean;
}

export function isValidHsCode(code: string): boolean {
  return /^\d{6}$/.test(code);
}

export function createCodeReview(code: string, suggestedCode: string | null): CodeReview {
  return { code, changed: code !== suggestedCode };
}

function confidenceColor(c: number): string {
  if (c >= 0.85) return "bg-emerald-100 text-emerald-800";
  if (c >= 0.7) return "bg-amber-100 text-amber-800";
  return "bg-rose-100 text-rose-800";
}

function statusBadge(status: "classified" | "ambiguous" | "error"): string {
  if (status === "classified") return "bg-emerald-100 text-emerald-800";
  if (status === "ambiguous") return "bg-amber-100 text-amber-800";
  return "bg-rose-100 text-rose-800";
}

export function ResultTable({ items }: Props) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const [reviews, setReviews] = useState<Record<number, CodeReview>>({});
  const s = t().results;

  function acceptCode(index: number, code: string) {
    if (!isValidHsCode(code)) return;
    setReviews((current) => ({
      ...current,
      [index]: createCodeReview(code, code),
    }));
  }

  function saveCode(index: number, code: string, suggestedCode: string | null) {
    setReviews((current) => ({
      ...current,
      [index]: createCodeReview(code, suggestedCode),
    }));
  }

  function resetCode(index: number) {
    setReviews((current) => {
      const next = { ...current };
      delete next[index];
      return next;
    });
  }

  if (!items.length) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
        {s.noneFound}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500">
        {s.itemsCount(items.length)}
      </div>
      <table className="min-w-full divide-y divide-slate-200">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="w-10 px-3 py-2 text-right">{s.columns.n}</th>
            <th className="px-3 py-2 text-left">{s.columns.desc}</th>
            <th className="w-52 px-3 py-2 text-left">{s.columns.code}</th>
            <th className="px-3 py-2 text-left">{s.columns.hsDesc}</th>
            <th className="w-24 px-3 py-2 text-right">{s.columns.conf}</th>
            <th className="w-32 px-3 py-2 text-left">{s.columns.status}</th>
            <th className="w-16 px-3 py-2"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((it, idx) => {
            const lineIndex = (it.line_number ?? idx + 1) - 1;
            const r = it.classification;
            const result = r.result;
            const status = r.status;
            const suggestedCode = result?.primary_code ?? null;
            const code = reviews[lineIndex]?.code ?? suggestedCode ?? "—";
            const hsDesc = result?.primary_description ?? "";
            const conf = result?.confidence ?? 0;
            const open = openIdx === lineIndex;

            return (
              <FragmentRow
                key={lineIndex}
                idx={lineIndex}
                it={it}
                result={result}
                open={open}
                status={status}
                code={code}
                suggestedCode={suggestedCode}
                review={reviews[lineIndex]}
                hsDesc={hsDesc}
                conf={conf}
                statusColors={statusBadge(status)}
                confidenceColors={confidenceColor(conf)}
                onAccept={() => acceptCode(lineIndex, suggestedCode ?? "")}
                onSave={(newCode) => saveCode(lineIndex, newCode, suggestedCode)}
                onReset={() => resetCode(lineIndex)}
                onToggle={() => setOpenIdx(open ? null : lineIndex)}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface RowProps {
  idx: number;
  it: InvoiceItem;
  result: ClassificationResult | null;
  open: boolean;
  status: "classified" | "ambiguous" | "error";
  code: string;
  suggestedCode: string | null;
  review?: CodeReview;
  hsDesc: string;
  conf: number;
  statusColors: string;
  confidenceColors: string;
  onAccept: () => void;
  onSave: (code: string) => void;
  onReset: () => void;
  onToggle: () => void;
}

function FragmentRow(props: RowProps) {
  const {
    idx, it, result, open, status, code, suggestedCode, review, hsDesc, conf,
    statusColors, confidenceColors, onAccept, onSave, onReset, onToggle,
  } = props;
  const s = t().results;
  const [editing, setEditing] = useState(false);
  const [draftCode, setDraftCode] = useState("");
  const [codeError, setCodeError] = useState<string | null>(null);

  function startEditing() {
    setDraftCode(code !== "—" ? code : suggestedCode ?? "");
    setCodeError(null);
    setEditing(true);
  }

  function saveCode() {
    if (!isValidHsCode(draftCode)) {
      setCodeError(s.invalidHsCode);
      return;
    }
    onSave(draftCode);
    setEditing(false);
  }

  return (
    <>
      <tr className="bg-white hover:bg-slate-50">
        <td className="px-3 py-2 text-right text-xs text-slate-400">{idx + 1}</td>
        <td className="px-3 py-2 text-sm text-slate-800">{it.description}</td>
        <td className="px-3 py-2">
          <div className="flex flex-wrap items-center gap-1">
            <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700">
              {code}
            </span>
            {review && (
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] text-emerald-700">
                {s.accepted}
              </span>
            )}
            {review?.changed && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] text-amber-700">
                {s.modified}
              </span>
            )}
          </div>
          {editing ? (
            <form
              className="mt-2 w-44"
              onSubmit={(event) => {
                event.preventDefault();
                saveCode();
              }}
            >
              <input
                autoFocus
                aria-label={s.change}
                inputMode="numeric"
                maxLength={6}
                pattern="[0-9]{6}"
                value={draftCode}
                onChange={(event) => {
                  setDraftCode(event.target.value.replace(/\D/g, "").slice(0, 6));
                  setCodeError(null);
                }}
                className="w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-200"
              />
              {codeError && <p className="mt-1 text-[10px] text-red-600">{codeError}</p>}
              <div className="mt-1 flex gap-2">
                <button
                  type="submit"
                  className="text-xs font-medium text-blue-600 hover:underline"
                >
                  {s.save}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditing(false);
                    setCodeError(null);
                  }}
                  className="text-xs text-slate-500 hover:underline"
                >
                  {s.cancel}
                </button>
              </div>
            </form>
          ) : (
            <div className="mt-2 flex flex-wrap gap-2">
              {!review && suggestedCode && isValidHsCode(suggestedCode) && (
                <button
                  type="button"
                  onClick={onAccept}
                  className="text-xs font-medium text-emerald-700 hover:underline"
                >
                  {s.accept}
                </button>
              )}
              <button
                type="button"
                onClick={startEditing}
                className="text-xs text-blue-600 hover:underline"
              >
                {s.change}
              </button>
              {review && (
                <button
                  type="button"
                  onClick={onReset}
                  className="text-xs text-slate-500 hover:underline"
                >
                  {s.reset}
                </button>
              )}
            </div>
          )}
        </td>
        <td className="px-3 py-2 text-sm text-slate-600">
          {review?.changed ? s.manualDescription : hsDesc}
        </td>
        <td className="px-3 py-2 text-right">
          {review?.changed ? (
            <span className="text-xs text-slate-400">—</span>
          ) : (
            <span className={`rounded-full px-2 py-0.5 text-xs ${confidenceColors}`}>
              {(conf * 100).toFixed(0)}%
            </span>
          )}
        </td>
        <td className="px-3 py-2">
          <div className="flex flex-wrap items-center gap-1">
            {review?.changed ? (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                {s.reviewed}
              </span>
            ) : (
              <span className={`rounded-full px-2 py-0.5 text-xs ${statusColors}`}>
                {s.status[status]}
              </span>
            )}
            {result?.total_tokens ? (
              <span
                className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-600"
                title={`${result.prompt_tokens} entrada · ${result.output_tokens} salida`}
              >
                {result.total_tokens.toLocaleString("es-ES")} tok
              </span>
            ) : null}
          </div>
        </td>
        <td className="px-3 py-2 text-right">
          <button
            type="button"
            onClick={onToggle}
            className="text-xs text-blue-600 hover:underline"
          >
            {open ? "−" : "+"}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="bg-slate-50/50">
          <td colSpan={7} className="px-6 py-4">
            <div className="mb-2 text-xs uppercase tracking-wide text-slate-400">
              {s.columns.expand}
            </div>
            {review?.changed && (
              <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {s.originalProposal}
              </div>
            )}
            <DetailPanel response={it.classification} />
          </td>
        </tr>
      )}
    </>
  );
}
