import { useEffect, useMemo, useState } from "react";
import { ApiError, classifyRaw, fetchHealth, uploadInvoice } from "./api";
import { InvoiceUpload } from "./components/InvoiceUpload";
import { TextInput } from "./components/TextInput";
import { ResultTable } from "./components/ResultTable";
import {
  SUPPORTED_LANGS,
  getLang,
  setLang,
  t,
  type Lang,
} from "./i18n/strings";
import type { HealthResponse, InvoiceUploadResponse } from "./types";

type Tab = "upload" | "paste";

export default function App() {
  const [tab, setTab] = useState<Tab>("upload");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [result, setResult] = useState<InvoiceUploadResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);

  // Re-render when language changes
  const [, setLangVersion] = useState(0);
  const currentLang: Lang = getLang();
  const dict = t();

  useEffect(() => {
    let cancelled = false;
    fetchHealth()
      .then((h) => !cancelled && setHealth(h))
      .catch(() => !cancelled && setHealth(null));
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleFile(file: File) {
    setError(null);
    setWarning(null);
    setResult(null);
    setLoading(true);
    try {
      const res = await uploadInvoice(file);
      setResult(res);
      if (res.warning) setWarning(res.warning);
    } catch (e) {
      setError(humanizeError(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleText(text: string) {
    setError(null);
    setWarning(null);
    setResult(null);
    setLoading(true);
    try {
      const res = await classifyRaw(text);
      setResult(res);
      if (res.warning) setWarning(res.warning);
    } catch (e) {
      setError(humanizeError(e));
    } finally {
      setLoading(false);
    }
  }

  // Suma de tokens consumidos por toda la factura
  const tokensAgg = useMemo(() => {
    if (!result)
      return { in: 0, out: 0, all: 0, label: "" };
    let inn = 0;
    let outt = 0;
    for (const it of result.items) {
      const r = it.classification.result;
      if (!r) continue;
      inn += r.prompt_tokens ?? 0;
      outt += r.output_tokens ?? 0;
    }
    const all = inn + outt;
    const locale = currentLang === "en" ? "en-US" : "es-ES";
    const fmt = (n: number) => n.toLocaleString(locale);
    const label = all === 0
      ? ""
      : `${fmt(all)} tokens (${fmt(inn)} ↑ entrada / ${fmt(outt)} ↓ salida)`;
    return { in: inn, out: outt, all, label };
  }, [result, currentLang]);

  return (
    <div className="min-h-full">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-4">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">{dict.appTitle}</h1>
            <p className="mt-1 text-sm text-slate-500">{dict.appSubtitle}</p>
          </div>
          <div className="flex items-center gap-3">
            <div
              className={[
                "flex items-center gap-2 rounded-full px-3 py-1 text-xs",
                health?.tariffai_reachable
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-rose-50 text-rose-700",
              ].join(" ")}
              title={health?.tariffai_url ?? ""}
            >
              <span
                className={[
                  "h-2 w-2 rounded-full",
                  health?.tariffai_reachable ? "bg-emerald-500" : "bg-rose-500",
                ].join(" ")}
              />
              <span>
                {dict.tariffaiStatusLabel}:{" "}
                {health?.tariffai_reachable ? dict.tariffaiOk : dict.tariffaiKo}
              </span>
            </div>
            <LangSwitcher
              current={currentLang}
              onChange={(l) => {
                setLang(l);
                setLangVersion((v) => v + 1);
              }}
            />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 flex border-b border-slate-200">
            {(["upload", "paste"] as const).map((id) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={[
                  "px-4 py-2 text-sm font-medium transition-colors",
                  tab === id
                    ? "border-b-2 border-blue-600 text-blue-700"
                    : "text-slate-500 hover:text-slate-800",
                ].join(" ")}
              >
                {dict.tabs[id]}
              </button>
            ))}
          </div>

          {tab === "upload" ? (
            <InvoiceUpload loading={loading} onSubmit={handleFile} />
          ) : (
            <TextInput loading={loading} onSubmit={handleText} />
          )}
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {warning && !error && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <strong>{dict.results.warning}:</strong> {warning}
          </div>
        )}

        {result && (
          <section className="mt-6">
            <h2 className="mb-3 text-lg font-semibold text-slate-900">
              {dict.results.title} ·{" "}
              <span className="text-sm font-normal text-slate-500">
                {result.filename} · {result.source}
                {result.pages ? ` · ${result.pages} pág.` : ""}
                {tokensAgg.all > 0
                  ? ` · ${tokensAgg.label}`
                  : ""}
              </span>
            </h2>
            <ResultTable items={result.items} />
          </section>
        )}
      </main>

      <footer className="mx-auto max-w-5xl px-4 pb-10 pt-4 text-center text-xs text-slate-400">
        Powered by{" "}
        <a className="text-blue-600 hover:underline" href="/docs" target="_blank" rel="noreferrer">
          TariffAI
        </a>
        {" · "}
        <a className="hover:underline" href="/docs" target="_blank" rel="noreferrer">
          API docs
        </a>
      </footer>
    </div>
  );
}

function humanizeError(e: unknown): string {
  const dict = t();
  if (e instanceof ApiError) {
    const body = e.message.toLowerCase();
    if (e.status === 413 || body.includes("límite")) return dict.errors.tooBig;
    if (e.status === 400 || body.includes("no soportad")) return dict.errors.format;
    if (e.status === 502 || body.includes("tariffai")) return dict.errors.noApi;
    if (e.status === 0 || body.includes("failed to fetch")) return dict.errors.network;
    return e.message || dict.errors.submit;
  }
  return dict.errors.submit;
}

function LangSwitcher({ current, onChange }: { current: Lang; onChange: (l: Lang) => void }) {
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-slate-200 text-xs">
      {SUPPORTED_LANGS.map((l) => (
        <button
          key={l}
          onClick={() => onChange(l)}
          className={[
            "px-2 py-1 uppercase",
            l === current ? "bg-slate-800 text-white" : "bg-white text-slate-600 hover:bg-slate-100",
          ].join(" ")}
        >
          {l}
        </button>
      ))}
    </div>
  );
}
