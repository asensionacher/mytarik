import { useEffect, useRef, useState } from "react";
import { t } from "../i18n/strings";
import type { ClassificationResult } from "../types";

interface Props {
  result: ClassificationResult;
  description: string;
  onSelect: (code: string) => void;
  onClose: () => void;
}

/** Umbral de confianza a partir del cual la IA considera resuelta la línea. */
export const CONFIDENCE_THRESHOLD = 0.9;

/**
 * Códigos entre los que la IA duda: la propuesta principal más las
 * alternativas que justifica.
 *
 * El backend solo informa de la confianza de la propuesta principal, así que
 * las alternativas se devuelven sin porcentaje en lugar de inventar uno.
 *
 * Devuelve `[]` cuando no hay nada que decidir: sin código primario y sin
 * alternativas no se puede abrir el modal.
 */
export function buildDecisionCandidates(result: ClassificationResult): {
  code: string;
  description: string;
  confidence: number | null;
  isPrimary: boolean;
  why_not?: string | null;
  trade_off?: string | null;
}[] {
  const candidates: {
    code: string;
    description: string;
    confidence: number | null;
    isPrimary: boolean;
    why_not?: string | null;
    trade_off?: string | null;
  }[] = [];

  if (result.primary_code) {
    candidates.push({
      code: result.primary_code,
      description: result.primary_description ?? "",
      confidence: result.confidence,
      isPrimary: true,
    });
  }
  for (const alternative of result.alternative_codes ?? []) {
    if (!alternative?.code) continue;
    if (candidates.some((entry) => entry.code === alternative.code)) continue;
    candidates.push({
      code: alternative.code,
      description: alternative.description ?? "",
      confidence: null,
      isPrimary: false,
      why_not: alternative.why_not,
      trade_off: alternative.trade_off,
    });
  }
  return candidates;
}

/**
 * ¿La IA sigue dudando de esta línea?
 *
 * La duda se mide con la confianza: por debajo del umbral, o sin código
 * primario propuesto, la IA no ha cerrado la clasificación y hay que decidir
 * a mano. Con el umbral alcanzado la línea está resuelta aunque la IA haya
 * insertado alternativas en su razonamiento.
 */
export function needsCodeDecision(result: ClassificationResult): boolean {
  if (result.confidence >= CONFIDENCE_THRESHOLD && result.primary_code) return false;
  return buildDecisionCandidates(result).length > 1;
}

/**
 * Modal para que quien declara elija entre los códigos entre los que duda la
 * IA. La elección se registra como revisión manual del código, igual que el
 * botón "Aceptar" de la tabla.
 */
export function CodeDecisionModal({ result, description, onSelect, onClose }: Props) {
  const s = t().decision;
  const candidates = buildDecisionCandidates(result);
  const [selected, setSelected] = useState<string>(
    candidates.find((entry) => entry.isPrimary)?.code ?? candidates[0]?.code ?? "",
  );
  const dialogRef = useRef<HTMLDivElement>(null);

  // Cierra con Escape y mueve el foco al diálogo.
  useEffect(() => {
    if (typeof document === "undefined") return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    dialogRef.current?.focus();
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  if (!candidates.length) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={s.title}
        tabIndex={-1}
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-xl"
      >
        <header className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">{s.title}</h2>
          <p className="mt-1 text-sm text-slate-600">{s.help}</p>
          <p className="mt-2 truncate text-xs text-slate-500" title={description}>
            {description}
          </p>
        </header>

        <div className="px-5 py-4">
          <fieldset>
            <legend className="sr-only">{s.legend}</legend>
            <div className="space-y-2">
              {candidates.map((candidate) => {
                const active = selected === candidate.code;
                return (
                  <label
                    key={candidate.code}
                    className={[
                      "flex cursor-pointer items-start gap-3 rounded-xl border p-3",
                      active
                        ? "border-blue-500 bg-blue-50"
                        : "border-slate-200 hover:bg-slate-50",
                    ].join(" ")}
                  >
                    <input
                      type="radio"
                      name="hs-code-decision"
                      value={candidate.code}
                      checked={active}
                      onChange={() => setSelected(candidate.code)}
                      className="mt-1 h-4 w-4 border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700">
                          {candidate.code}
                        </span>
                        {candidate.isPrimary && (
                          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] text-blue-700">
                            {s.primary}
                          </span>
                        )}
                        {candidate.confidence !== null && (
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">
                            {(candidate.confidence * 100).toFixed(0)}%
                          </span>
                        )}
                      </span>
                      {candidate.description && (
                        <span className="mt-1 block text-sm text-slate-700">
                          {candidate.description}
                        </span>
                      )}
                      {candidate.why_not && (
                        <span className="mt-1 block text-xs text-slate-600">
                          <span className="font-semibold">{s.whyNot}:</span> {candidate.why_not}
                        </span>
                      )}
                      {candidate.trade_off && (
                        <span className="mt-0.5 block text-xs text-slate-600">
                          <span className="font-semibold">{s.tradeOff}:</span> {candidate.trade_off}
                        </span>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        </div>

        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            {s.cancel}
          </button>
          <button
            type="button"
            onClick={() => selected && onSelect(selected)}
            disabled={!selected}
            className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {s.confirm}
          </button>
        </footer>
      </div>
    </div>
  );
}
