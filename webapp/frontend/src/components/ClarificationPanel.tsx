import { useId, useState } from "react";
import { t } from "../i18n/strings";
import type { ClassificationResult, ClarificationAnswer } from "../types";

interface Props {
  result: ClassificationResult;
  onAnswer: (answers: ClarificationAnswer[]) => Promise<void>;
  disabled?: boolean;
}

export function ClarificationPanel({ result, onAnswer, disabled = false }: Props) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const s = t().clarification;
  const inputId = useId();
  const question = result.clarification_question;
  const answers = result.clarification_answers ?? [];

  async function submit(answer: string) {
    if (!question || disabled || busy || !answer.trim() || answers.length >= 3) return;
    setBusy(true);
    setError(null);
    try {
      await onAnswer([...answers, { question: question.question, answer: answer.trim() }]);
      setDraft("");
    } catch (e) {
      setError(e instanceof Error ? e.message : t().errors.submit);
    } finally {
      setBusy(false);
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
      {question && answers.length < 3 ? (
        <form onSubmit={(event) => { event.preventDefault(); void submit(draft); }}>
          <fieldset disabled={busy || disabled} className="space-y-3">
            <legend className="text-xs text-amber-800">{s.count(answers.length + 1)}</legend>
            <label className="block font-medium" htmlFor={inputId}>{question.question}</label>
            <div className="flex flex-wrap gap-2">
              {question.options.map((option, index) => (
                <button key={index} type="button" onClick={() => void submit(option)}
                  className="rounded-lg border border-amber-300 bg-white px-3 py-2 hover:bg-amber-100">
                  {option}
                </button>
              ))}
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
