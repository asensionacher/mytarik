import { t } from "../i18n/strings";
import type { ClassificationResult, ClassifyResponse } from "../types";

interface Props {
  response: ClassifyResponse;
}

export function DetailPanel({ response }: Props) {
  const dict = t();
  const s = dict.details;
  const tk = dict.tokens;
  const thinkingLabel = dict.detail?.thinking ?? "Razonamiento interno";
  const error = response.error;
  const result: ClassificationResult | null = response.result;

  if (response.status === "error" || !result) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        {error ?? "Error"}
      </div>
    );
  }

  const h = result.hierarchy ?? {};
  const reasons = result.reasoning;

  return (
    <div className="space-y-5 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
      <section>
        <div className="text-xs uppercase tracking-wide text-slate-500">{s.cleaned}</div>
        <div className="mt-1 italic text-slate-700">
          {result.cleaned_text || result.input_text}
        </div>
      </section>

      <section>
        <div className="text-xs uppercase tracking-wide text-slate-500">{s.hierarchy}</div>
        <ul className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {(["section", "chapter", "heading", "subheading"] as const).map((lvl) => {
            const entry = h[lvl];
            return (
              <li key={lvl} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                <div className="text-xs text-slate-500">{s.hierarchyLevels[lvl]}</div>
                {entry ? (
                  <div className="mt-0.5">
                    <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700">
                      {entry.code}
                    </span>
                    <span className="text-slate-700">{entry.description}</span>
                  </div>
                ) : (
                  <span className="text-slate-300">—</span>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <div className="text-xs uppercase tracking-wide text-slate-500">{s.reasoning}</div>
        <dl className="mt-1 space-y-1">
          {([
            ["section_reasoning", s.reasoningLevels.section],
            ["chapter_reasoning", s.reasoningLevels.chapter],
            ["heading_reasoning", s.reasoningLevels.heading],
            ["subheading_reasoning", s.reasoningLevels.subheading],
          ] as const).map(([k, label]) => (
            <div key={k} className="flex gap-2">
              <dt className="w-24 shrink-0 text-xs text-slate-500">{label}</dt>
              <dd className="text-slate-700">{reasons?.[k] || "—"}</dd>
            </div>
          ))}
        </dl>
      </section>

      {reasons?.key_factors?.length ? (
        <section>
          <div className="text-xs uppercase tracking-wide text-slate-500">{s.keyFactors}</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {reasons.key_factors.map((f, i) => (
              <span
                key={i}
                className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
              >
                {f}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {result.alternative_codes?.length ? (
        <section>
          <div className="text-xs uppercase tracking-wide text-slate-500">
            {s.alternatives}
          </div>
          <ul className="mt-1 space-y-2">
            {result.alternative_codes.map((alt) => (
              <li
                key={alt.code}
                className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <span className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-xs text-amber-800">
                    {alt.code}
                  </span>
                  <span className="text-sm text-amber-900">{alt.description}</span>
                </div>
                {alt.why_not ? (
                  <div className="mt-1 text-xs text-amber-800">
                    <span className="font-semibold">{s.whyNot}:</span> {alt.why_not}
                  </div>
                ) : null}
                {alt.trade_off ? (
                  <div className="mt-0.5 text-xs text-amber-800">
                    <span className="font-semibold">{s.tradeOff}:</span> {alt.trade_off}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {result.clarification_answers?.length ? (
        <section>
          <div className="text-xs uppercase tracking-wide text-slate-500">{s.answers}</div>
          <ul className="mt-1 space-y-1">
            {result.clarification_answers.map((answer, index) => (
              <li
                key={`${answer.question_id ?? index}`}
                className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs"
              >
                <div className="font-medium text-blue-900">{answer.question}</div>
                <div className="mt-0.5 text-blue-800">{answer.answer}</div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {result.reasoning_reasons?.length ? (
        <section>
          <div className="text-xs uppercase tracking-wide text-slate-500">
            {s.reasoningReasons}
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {result.reasoning_reasons.map((reason) => (
              <span
                key={reason}
                className="rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] text-indigo-700"
              >
                {reason}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      <section className="text-xs text-slate-400">{s.time(result.processing_time_ms)}</section>

      {result.thinking ? (
        <details className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs">
          <summary className="font-medium text-indigo-800">
            🧠 {thinkingLabel}
          </summary>
          <pre className="mt-2 whitespace-pre-wrap break-words text-[11px] leading-relaxed text-indigo-900">
            {result.thinking}
          </pre>
        </details>
      ) : null}

      <section className="border-t border-slate-200 pt-3">
        <div className="text-xs uppercase tracking-wide text-slate-500">
          {tk.title}
        </div>
        <div className="mt-1 grid grid-cols-3 gap-2 text-center">
          <TokenStat
            label={tk.prompt}
            value={result.prompt_tokens ?? 0}
          />
          <TokenStat
            label={tk.output}
            value={result.output_tokens ?? 0}
          />
          <TokenStat
            label={tk.total}
            value={result.total_tokens ?? 0}
            highlight
          />
        </div>
      </section>
    </div>
  );
}

function TokenStat({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: number;
  highlight?: boolean;
}) {
  const cls = highlight
    ? "border-blue-200 bg-blue-50"
    : "border-slate-200 bg-white";
  return (
    <div className={`rounded-lg border px-2 py-1.5 ${cls}`}>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="font-mono text-sm font-semibold text-slate-800">
        {(value ?? 0).toLocaleString("es-ES")}
      </div>
    </div>
  );
}
