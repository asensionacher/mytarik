import { useState } from "react";
import { t } from "../i18n/strings";
import type { ClassificationResult, InvoiceItem } from "../types";
import { DetailPanel } from "./DetailPanel";

interface Props {
  items: InvoiceItem[];
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
  const s = t().results;

  if (!items.length) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
        {s.noneFound}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500">
        {s.itemsCount(items.length)}
      </div>
      <table className="min-w-full divide-y divide-slate-200">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="w-10 px-3 py-2 text-right">{s.columns.n}</th>
            <th className="px-3 py-2 text-left">{s.columns.desc}</th>
            <th className="w-28 px-3 py-2 text-left">{s.columns.code}</th>
            <th className="px-3 py-2 text-left">{s.columns.hsDesc}</th>
            <th className="w-24 px-3 py-2 text-right">{s.columns.conf}</th>
            <th className="w-32 px-3 py-2 text-left">{s.columns.status}</th>
            <th className="w-16 px-3 py-2"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((it, idx) => {
            const r = it.classification;
            const result = r.result;
            const status = r.status;
            const code = result?.primary_code ?? "—";
            const hsDesc = result?.primary_description ?? "";
            const conf = result?.confidence ?? 0;
            const open = openIdx === idx;

            return (
              <FragmentRow
                key={`${idx}-${code}`}
                idx={idx}
                it={it}
                result={result}
                open={open}
                status={status}
                code={code}
                hsDesc={hsDesc}
                conf={conf}
                statusColors={statusBadge(status)}
                confidenceColors={confidenceColor(conf)}
                onToggle={() => setOpenIdx(open ? null : idx)}
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
  hsDesc: string;
  conf: number;
  statusColors: string;
  confidenceColors: string;
  onToggle: () => void;
}

function FragmentRow(props: RowProps) {
  const { idx, it, result, open, status, code, hsDesc, conf, statusColors, confidenceColors, onToggle } =
    props;
  const s = t().results;

  return (
    <>
      <tr className="bg-white hover:bg-slate-50">
        <td className="px-3 py-2 text-right text-xs text-slate-400">{idx + 1}</td>
        <td className="px-3 py-2 text-sm text-slate-800">{it.description}</td>
        <td className="px-3 py-2">
          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700">
            {code}
          </span>
        </td>
        <td className="px-3 py-2 text-sm text-slate-600">{hsDesc}</td>
        <td className="px-3 py-2 text-right">
          <span className={`rounded-full px-2 py-0.5 text-xs ${confidenceColors}`}>
            {(conf * 100).toFixed(0)}%
          </span>
        </td>
        <td className="px-3 py-2">
          <div className="flex flex-wrap items-center gap-1">
            <span className={`rounded-full px-2 py-0.5 text-xs ${statusColors}`}>
              {s.status[status]}
            </span>
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
            <DetailPanel response={it.classification} />
          </td>
        </tr>
      )}
    </>
  );
}
