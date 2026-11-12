import { useEffect, useId, useRef, useState } from "react";
import { t } from "../i18n/strings";
import type { ClassificationResult, ClarificationAnswer } from "../types";

interface Props {
  result: ClassificationResult;
  onAnswer: (answers: ClarificationAnswer[]) => Promise<void>;
  disabled?: boolean;
}

/**
 * ¿La opción corresponde a la respuesta que se está procesando?
 *
 * Se compara sin distinguir mayúsculas ni espacios sobrantes, porque la
 * opción del botón y la respuesta enviada son el mismo texto.
 */
export function isSelectedOption(option: string, pending: string | null): boolean {
  if (!pending) return false;
  return option.trim().toLowerCase() === pending.trim().toLowerCase();
}

export function ClarificationPanel({ result, onAnswer, disabled = false }: Props) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  // Opción pulsada: se marca mientras la IA procesa la respuesta.
  const [pendingOption, setPendingOption] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const s = t().clarification;
  const inputId = useId();
  const question = result.clarification_question;
  const answers = result.clarification_answers ?? [];
  const startedAt = useRef<number | null>(null);

  // Tiempo transcurrido desde que se envió la respuesta.
  useEffect(() => {
    if (!busy) {
      startedAt.current = null;
      setElapsed(0);
      return;
    }
    const timer = window.setInterval(() => {
      if (startedAt.current) setElapsed(Math.floor((Date.now() - startedAt.current) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  async function submit(answer: string) {
    if (!question || disabled || busy || !answer.trim() || answers.length >= 3) return;
    setBusy(true);
    setPendingOption(answer.trim());
    setError(null);
    startedAt.current = Date.now();
    try {
      await onAnswer([...answers, { question: question.question, answer: answer.trim() }]);
      setDraft("");
    } catch (e) {
      setError(e instanceof Error ? e.message : t().errors.submit);
    } finally {
      setBusy(false);
      setPendingOption(null);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm">
      <h3 className="font-semibold text-amber-900">{s.title}</h3>
      {answers.map((answer, index) => (
        <dl key={index}>
          <dt className="font-medium">{answer.question}</dt>
          <dd className="text-slate-600">{answer.answer}</dd>
        </dl>
      ))}
      {busy && (
        <p role="status" aria-live="polite" className="flex items-center gap-2 text-xs text-amber-800">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-amber-600 border-t-transparent"
          />
          {s.thinking}
          {elapsed > 0 && <span className="text-amber-700">· {s.elapsed(elapsed)}</span>}
        </p>
      )}
      {question && answers.length < 3 ? (
        <form onSubmit={(event) => { event.preventDefault(); void submit(draft); }}>
          <fieldset disabled={busy || disabled} className="space-y-3">
            <legend className="text-xs text-amber-800">{s.count(answers.length + 1)}</legend>
            <label className="block font-medium" htmlFor={inputId}>{question.question}</label>
            <div className="flex flex-wrap gap-2">
              {question.options.map((option, index) => {
                const selected = isSelectedOption(option, pendingOption);
                return (
                  <button
                    key={index}
                    type="button"
                    onClick={() => void submit(option)}
                    aria-pressed={selected}
                    className={[
                      "rounded-lg border px-3 py-2",
                      selected
                        ? "border-blue-600 bg-blue-100 font-medium text-blue-900"
                        : "border-amber-300 bg-white hover:bg-amber-100",
                    ].join(" ")}
                  >
                    {selected && <span aria-hidden="true">✓ </span>}
                    {option}
                  </button>
                );
              })}
            </div>
            <input id={inputId} value={draft} maxLength={2000} disabled={busy}
              onChange={(event) => setDraft(event.target.value)} placeholder={s.answer}
              className="w-full rounded-lg border border-slate-300 px-3 py-2" />
            <button type="submit" disabled={busy || !draft.trim()}
              className="rounded-lg bg-blue-600 px-3 py-2 text-white disabled:opacity-50">
              {busy ? s.loading : s.send}
            </button>
          </fieldset>
        </form>
      ) : result.needs_human_review ? <p>{s.review}</p> : null}
      {error && <p role="alert" className="text-red-700">{error}</p>}
    </section>
  );
}
