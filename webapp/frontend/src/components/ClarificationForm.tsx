import { useMemo, useState } from "react";
import { t } from "../i18n/strings";
import type { ClarificationAnswer, ClarificationQuestion } from "../types";

interface Props {
  questions: ClarificationQuestion[];
  busy?: boolean;
  error?: string | null;
  onSubmit: (answers: ClarificationAnswer[]) => void;
}

/**
 * Formulario de aclaración: la IA pregunta lo justo para fijar el código HS.
 * Cada pregunta se responde con botones (opciones del catálogo) o escribiendo
 * una respuesta libre.
 */
export function ClarificationForm({ questions, busy = false, error = null, onSubmit }: Props) {
  const s = t().results.clarify;
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [written, setWritten] = useState<Record<string, string>>({});

  const answered = useMemo(() => {
    const map: Record<string, string> = {};
    for (const question of questions) {
      const free = (written[question.id] ?? "").trim();
      if (free) {
        map[question.id] = free;
        continue;
      }
      const option = picked[question.id];
      if (option) map[question.id] = option;
    }
    return map;
  }, [picked, written, questions]);

  const complete = questions.length > 0 && questions.every((q) => Boolean(answered[q.id]));

  function select(questionId: string, value: string) {
    setPicked((current) => ({ ...current, [questionId]: value }));
    setWritten((current) => {
      if (!(questionId in current)) return current;
      const next = { ...current };
      delete next[questionId];
      return next;
    });
  }

  function type(questionId: string, value: string) {
    setWritten((current) => ({ ...current, [questionId]: value }));
  }

  function submit() {
    if (!complete || busy) return;
    onSubmit(
      questions.map((question) => ({
        question_id: question.id,
        question: question.question,
        answer: answered[question.id],
      })),
    );
  }

  if (!questions.length) return null;

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50/70 p-3">
      <div className="text-sm font-semibold text-blue-900">{s.title}</div>
      <p className="mt-0.5 text-xs text-blue-800">{s.subtitle}</p>

      <ol className="mt-3 space-y-3">
        {questions.map((question, index) => {
          const current = answered[question.id] ?? "";
          return (
            <li key={question.id} className="rounded-md border border-blue-100 bg-white p-3">
              <div className="text-xs font-medium uppercase tracking-wide text-blue-700">
                {s.question(index + 1, questions.length)}
              </div>
              <div className="mt-0.5 text-sm text-slate-800">{question.question}</div>
              {question.hint ? (
                <div className="mt-1 text-xs italic text-slate-500">{question.hint}</div>
              ) : null}

              {question.options?.length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {question.options.map((option) => {
                    const active = current === option.value && !(written[question.id] ?? "").trim();
                    return (
                      <button
                        key={option.value}
                        type="button"
                        disabled={busy}
                        onClick={() => select(question.id, option.value)}
                        title={option.description ?? option.code ?? undefined}
                        className={[
                          "rounded-full border px-2.5 py-1 text-xs transition-colors",
                          active
                            ? "border-blue-600 bg-blue-600 text-white"
                            : "border-blue-200 bg-blue-50 text-blue-800 hover:bg-blue-100",
                          busy ? "cursor-not-allowed opacity-60" : "",
                        ].join(" ")}
                      >
                        {option.label || option.value}
                        {option.code ? (
                          <span className="ml-1 font-mono text-[10px] opacity-80">{option.code}</span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {question.allow_free_text !== false ? (
                <input
                  type="text"
                  disabled={busy}
                  value={written[question.id] ?? ""}
                  onChange={(event) => type(question.id, event.target.value)}
                  placeholder={s.freeText}
                  aria-label={question.question}
                  className="mt-2 w-full rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-200"
                />
              ) : null}
            </li>
          );
        })}
      </ol>

      {error ? <div className="mt-2 text-xs text-red-600">{error}</div> : null}

      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          disabled={!complete || busy}
          onClick={submit}
          className={[
            "rounded-lg px-3 py-1.5 text-xs font-medium",
            complete && !busy
              ? "bg-blue-600 text-white hover:bg-blue-700"
              : "cursor-not-allowed bg-slate-200 text-slate-400",
          ].join(" ")}
        >
          {busy ? s.submitting : s.submit}
        </button>
        {!complete ? <span className="text-[11px] text-blue-800">{s.answerRequired}</span> : null}
      </div>
    </div>
  );
}
