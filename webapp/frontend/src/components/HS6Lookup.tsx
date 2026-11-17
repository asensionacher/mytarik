import { useState } from "react";
import { hs6Lookup } from "../api";
import { t } from "../i18n/strings";
import type { HS6LookupResponse } from "../types";

export function HS6Lookup() {
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<HS6LookupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const s = t().hs6;

  async function handleSubmit() {
    if (!query.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const res = await hs6Lookup(query.trim(), 5);
      setResult(res);
    } catch (e) {
      setError(s.error);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="mb-1 text-lg font-semibold text-slate-900">{s.title}</h2>
      <p className="mb-4 text-sm text-slate-500">{s.subtitle}</p>

      <div className="mb-3">
        <label className="mb-1 block text-xs font-medium text-slate-600">
          {s.label}
        </label>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={s.placeholder}
          rows={4}
          disabled={submitting}
          className="block w-full resize-y rounded-xl border border-slate-300 bg-white p-3 font-mono text-sm shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-200 disabled:opacity-60"
        />
      </div>

      <button
        type="button"
        disabled={!query.trim() || submitting}
        onClick={handleSubmit}
        className={[
          "w-full rounded-xl px-4 py-3 text-base font-medium text-white shadow-sm transition-colors",
          !query.trim() || submitting
            ? "bg-slate-300 cursor-not-allowed"
            : "bg-blue-600 hover:bg-blue-700",
        ].join(" ")}
      >
        {submitting ? s.submitting : s.submit}
      </button>

      {result && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <strong>{s.notice}</strong>
        </div>
      )}

      {result && result.candidates.length > 0 && (
        <table className="mt-4 w-full table-auto border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left">
              <th className="pb-2 text-slate-600">HS6</th>
              <th className="pb-2 text-slate-600">Descripción</th>
              <th className="pb-2 text-right text-slate-600">Score</th>
            </tr>
          </thead>
          <tbody>
            {result.candidates.map((c) => (
              <tr key={c.hs6} className="border-b border-slate-100">
                <td className="py-2 font-medium text-slate-800">{c.hs6}</td>
                <td className="py-2 text-slate-700">{c.description}</td>
                <td className="py-2 text-right">{s.score(c.score)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {result && result.candidates.length === 0 && (
        <p className="mt-4 text-sm text-slate-500">{s.noResults}</p>
      )}

      {error && (
        <p className="mt-4 text-sm text-rose-600">{error}</p>
      )}
    </section>
  );
}
