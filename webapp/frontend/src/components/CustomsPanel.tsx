import { useState } from "react";
import { evaluateCustomsOperation, resolveTaricCodes } from "../api";
import { t } from "../i18n/strings";
import type {
  CodeReview,
  CustomsOperationResponse,
  InvoiceItem,
  ItemMeasures,
  TaricCandidate,
  TradeDetails,
} from "../types";

interface Props {
  items: InvoiceItem[];
  reviews: Record<number, CodeReview>;
  trade: TradeDetails;
  onError: (message: string) => void;
}

type Stage = "idle" | "resolving" | "choosing" | "evaluating" | "done";

interface Line {
  index: number;
  item: InvoiceItem;
  hsCode: string;
}

export interface CustomsLineInput {
  taric_code: string;
  description: string;
  customs_value?: number;
  currency?: string;
  net_weight_kg?: number;
}

/**
 * Traduce el contexto de la UI al contrato del motor de medidas.
 *
 * El país de expedición de la UI es el país de destino de la operación: es
 * donde se despacha la mercancía y, en una importación, el Estado Miembro que
 * aplica el arancel.
 */
export function buildOperationPayload(
  lines: Line[],
  selected: Record<number, string>,
  amounts: Record<number, { value: string; weight: string }>,
  trade: TradeDetails,
): {
  operation_type: "IMPORT" | "EXPORT";
  origin_country: string;
  destination_country: string;
  items: CustomsLineInput[];
} {
  const items = lines.map((line) => {
    const amount = amounts[line.index] ?? { value: "", weight: "" };
    const value = Number(amount.value);
    const weight = Number(amount.weight);
    return {
      taric_code: selected[line.index] || line.hsCode,
      description: line.item.description,
      customs_value: amount.value && value > 0 ? value : undefined,
      currency: amount.value && value > 0 ? "EUR" : undefined,
      net_weight_kg: amount.weight && weight > 0 ? weight : undefined,
    };
  });
  return {
    operation_type: trade.trade_mode === "import" ? "IMPORT" : "EXPORT",
    origin_country: trade.origin_country,
    destination_country: trade.dispatch_country,
    items,
  };
}

export function CustomsPanel({ items, reviews, trade, onError }: Props) {
  const s = t().customs;
  const [stage, setStage] = useState<Stage>("idle");
  const [candidates, setCandidates] = useState<Record<number, TaricCandidate[]>>({});
  const [selected, setSelected] = useState<Record<number, string>>({});
  const [amounts, setAmounts] = useState<Record<number, { value: string; weight: string }>>({});
  const [response, setResponse] = useState<CustomsOperationResponse | null>(null);
  const [notices, setNotices] = useState<string[]>([]);

  // El código aceptado o corregido manda sobre la propuesta del clasificador.
  const lines: Line[] = items
    .map((item, position) => {
      const index = (item.line_number ?? position + 1) - 1;
      const suggested = item.classification.result?.primary_code ?? null;
      return { index, item, hsCode: reviews[index]?.code ?? suggested ?? "" };
    })
    .filter((line) => /^\d{6}$/.test(line.hsCode));

  async function handleResolve() {
    setStage("resolving");
    setNotices([]);
    setResponse(null);
    try {
      const codes = [...new Set(lines.map((line) => line.hsCode))];
      const resolved = await Promise.all(codes.map(async (code) => {
        const result = await resolveTaricCodes(code, trade.dispatch_country);
        return [code, result] as const;
      }));
      const map: Record<number, TaricCandidate[]> = {};
      const chosen: Record<number, string> = {};
      const warnings: string[] = [];
      for (const [code, result] of resolved) {
        warnings.push(...result.warnings);
        for (const line of lines.filter((entry) => entry.hsCode === code)) {
          map[line.index] = result.candidates;
          if (result.candidates.length === 1) {
            chosen[line.index] = result.candidates[0].taric_code;
          }
        }
      }
      setCandidates(map);
      setSelected(chosen);
      setNotices(warnings);
      setStage("choosing");
    } catch {
      onError(t().errors.submit);
      setStage("idle");
    }
  }

  async function handleEvaluate() {
    setStage("evaluating");
    try {
      const result = await evaluateCustomsOperation(
        buildOperationPayload(lines, selected, amounts, trade),
      );
      setResponse(result);
      setStage("done");
    } catch {
      onError(t().errors.submit);
      setStage("choosing");
    }
  }

  if (!lines.length) {
    return (
      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">
        {t().results.noneFound}
      </div>
    );
  }

  return (
    <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-slate-900">{s.title}</h3>
      <p className="mt-1 text-xs text-slate-500">{s.help}</p>

      {stage === "idle" && (
        <button
          type="button"
          onClick={handleResolve}
          className="mt-3 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          {s.evaluate}
        </button>
      )}

      {(stage === "resolving" || stage === "evaluating") && (
        <p role="status" aria-live="polite" className="mt-3 text-sm text-slate-600">
          {stage === "resolving" ? s.resolving : s.evaluating}
        </p>
      )}

      {notices.length > 0 && (
        <ul className="mt-3 space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {notices.map((notice) => <li key={notice}>{notice}</li>)}
        </ul>
      )}

      {stage === "choosing" && (
        <div className="mt-3 space-y-3">
          {lines.map((line) => {
            const options = candidates[line.index] ?? [];
            const chosen = selected[line.index] ?? "";
            const several = options.length > 1;
            return (
              <div key={line.index} className="rounded-lg border border-slate-200 p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm text-slate-800">{line.item.description}</span>
                  <span className="font-mono text-xs text-slate-500">HS {line.hsCode}</span>
                </div>

                {several ? (
                  <>
                    <p className="mt-1 text-xs text-amber-800">{s.multiple}</p>
                    <select
                      aria-label={s.selectTaric}
                      value={chosen}
                      onChange={(event) =>
                        setSelected((current) => ({ ...current, [line.index]: event.target.value }))}
                      className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 font-mono text-xs focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-200"
                    >
                      <option value="">—</option>
                      {options.map((option) => (
                        <option key={option.taric_code} value={option.taric_code}>
                          {option.taric_code} · {option.description || s.inferred}
                        </option>
                      ))}
                    </select>
                  </>
                ) : (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <input
                      aria-label={s.selectTaric}
                      inputMode="numeric"
                      maxLength={10}
                      value={chosen}
                      placeholder={s.taricManual}
                      onChange={(event) =>
                        setSelected((current) => ({
                          ...current,
                          [line.index]: event.target.value.replace(/\D/g, "").slice(0, 10),
                        }))}
                      className="w-40 rounded-lg border border-slate-300 px-2 py-1.5 font-mono text-xs focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-200"
                    />
                    <span className="text-[11px] text-slate-500">
                      {options[0]?.exact ? s.taricResolved : s.taricInferred}
                    </span>
                  </div>
                )}

                <div className="mt-2 flex flex-wrap gap-3">
                  <label className="flex items-center gap-1 text-[11px] text-slate-500">
                    {s.value} (EUR)
                    <input
                      inputMode="decimal"
                      value={amounts[line.index]?.value ?? ""}
                      onChange={(event) => setAmounts((current) => ({
                        ...current,
                        [line.index]: {
                          value: event.target.value,
                          weight: current[line.index]?.weight ?? "",
                        },
                      }))}
                      className="w-24 rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-400 focus:outline-none"
                    />
                  </label>
                  <label className="flex items-center gap-1 text-[11px] text-slate-500">
                    {s.weight} (kg)
                    <input
                      inputMode="decimal"
                      value={amounts[line.index]?.weight ?? ""}
                      onChange={(event) => setAmounts((current) => ({
                        ...current,
                        [line.index]: {
                          value: current[line.index]?.value ?? "",
                          weight: event.target.value,
                        },
                      }))}
                      className="w-24 rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-400 focus:outline-none"
                    />
                  </label>
                </div>
              </div>
            );
          })}

          <button
            type="button"
            onClick={handleEvaluate}
            className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            {s.calculate}
          </button>
        </div>
      )}

      {stage === "done" && response && (
        <div className="mt-4 space-y-3">
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
            <p>
              <strong>{s.regime}:</strong> {response.customs_regime}
            </p>
            {response.reporting_requirements.length > 0 && (
              <p className="mt-1">
                <strong>{s.reporting}:</strong> {response.reporting_requirements.join(", ")}
              </p>
            )}
            {response.territorial_note && (
              <p className="mt-1 text-slate-600">{response.territorial_note}</p>
            )}
          </div>

          {response.items_measures.map((measures) => (
            <MeasureCard key={measures.line_number} measures={measures} />
          ))}

          <button
            type="button"
            onClick={handleResolve}
            className="text-xs font-medium text-blue-600 hover:underline"
          >
            {s.recalculate}
          </button>
        </div>
      )}
    </section>
  );
}

function MeasureCard({ measures }: { measures: ItemMeasures }) {
  const s = t().customs;
  const duty = measures.third_country_duty;
  const defense = measures.trade_defense_measures;
  const summary = measures.executive_summary;

  return (
    <article className="rounded-lg border border-slate-200 p-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-slate-800">
          {s.line} {measures.line_number} · <span className="font-mono">{measures.taric_code}</span>
        </span>
        <span className="text-[11px] text-slate-400">
          {s.source}: {measures.provenance.cache_hit ? s.cache : s.live}
        </span>
      </header>
      <p className="mt-0.5 text-xs text-slate-500">{measures.description}</p>

      {summary?.duty_to_pay && (
        <p className="mt-2 rounded-md bg-blue-50 px-2 py-1.5 text-xs text-blue-900">
          {summary.duty_to_pay}
        </p>
      )}

      {duty && (
        <p className="mt-2 text-xs text-slate-700">
          <strong>{s.baseDuty}:</strong> {duty.duty.formula_raw || "—"}
          {duty.variants.length > 0 && (
            <span className="ml-1 text-slate-500">
              ({duty.variants.map((variant) => variant.duty.formula_raw).filter(Boolean).join(" · ")})
            </span>
          )}
        </p>
      )}

      {measures.preferential_duties.length > 0 && (
        <p className="mt-1 text-xs text-slate-700">
          <strong>{s.preferences}:</strong>{" "}
          {measures.preferential_duties
            .map((preference) =>
              `${preference.agreement} ${preference.duty.formula_raw}`.trim())
            .join(" · ")}
        </p>
      )}

      {defense.length > 0 && (
        <p className="mt-1 text-xs text-slate-700">
          <strong>{s.defense}:</strong>{" "}
          {defense.slice(0, 3).map((measure) =>
            `${measure.additional_code ?? ""} ${measure.duty.formula_raw}`.trim()
          ).join(" · ")}
          {defense.length > 3 && ` · ${s.defenseMore(defense.length - 3)}`}
        </p>
      )}

      {measures.border_controls_and_inspections.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-medium text-slate-700">{s.controls}</p>
          <ul className="mt-1 list-disc pl-4 text-xs text-slate-600">
            {measures.border_controls_and_inspections.slice(0, 5).map((control) => (
              <li key={`${control.code}-${control.title}`}>
                {control.code} · {control.title}
              </li>
            ))}
          </ul>
        </div>
      )}

      {measures.environmental_and_special_regulations.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-medium text-slate-700">{s.regulations}</p>
          <ul className="mt-1 list-disc pl-4 text-xs text-slate-600">
            {measures.environmental_and_special_regulations.slice(0, 5).map((regulation) => (
              <li key={`${regulation.regulation}-${regulation.name}`}>
                {regulation.name}
                {regulation.reference ? ` (${regulation.reference})` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {measures.exemption_y_codes.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-medium text-slate-700">{s.yCodes}</p>
          <ul className="mt-1 list-disc pl-4 font-mono text-xs text-slate-700">
            {measures.exemption_y_codes.map((code) => (
              <li key={code.code}>{code.code} · {code.description}</li>
            ))}
          </ul>
        </div>
      )}

      {measures.tax_estimation && (
        <p className="mt-2 text-xs text-slate-700">
          <strong>{s.tax}:</strong> {measures.tax_estimation.currency}{" "}
          {measures.tax_estimation.estimated_duty.toFixed(2)} ·{" "}
          {measures.tax_estimation.estimated_vat !== null
            ? `IVA ${measures.tax_estimation.estimated_vat.toFixed(2)}`
            : "—"}
        </p>
      )}

      {!duty && !measures.preferential_duties.length && !defense.length && (
        <p className="mt-2 text-xs text-slate-500">{s.noMeasures}</p>
      )}

      {summary?.warnings?.map((warning) => (
        <p key={warning} className="mt-1 text-xs text-amber-800">{warning}</p>
      ))}
    </article>
  );
}
