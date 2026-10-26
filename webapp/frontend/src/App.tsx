import { useEffect, useMemo, useState } from "react";
import { ApiError, answerClarification, classifyRaw, fetchHealth, uploadInvoice } from "./api";
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
import type {
  ClassificationProgress,
  HealthResponse,
  InvoiceUploadResponse,
  TradeDetails,
  TradeMode,
  ClarificationAnswer,
} from "./types";

type Tab = "upload" | "paste";

const COUNTRY_CODES = (
  "AW AF AO AI AX AL AD AE AR AM AS AQ TF AG AU AT AZ BI BE BJ BQ BF BD BG BH BS " +
  "BA BL BY BZ BM BO BR BB BN BT BV BW CF CA CC CH CL CN CI CM CD CG CK CO KM CV " +
  "CR CU CW CX KY CY CZ DE DJ DM DK DO DZ EC EG ER EH ES EE ET FI FJ FK FR FO FM " +
  "GA GB GE GG GH GI GN GP GM GW GQ GR GD GL GT GF GU GY HK HM HN HR HT HU ID IM IN " +
  "IO IE IR IQ IS IL IT JM JE JO JP KZ KE KG KH KI KN KR KW LA LB LR LY LC LI LK " +
  "LS LT LU LV MO MF MA MC MD MG MV MX MH MK ML MT MM ME MN MP MZ MR MS MQ MU MW MY " +
  "YT NA NC NE NF NG NI NU NL NO NP NR NZ OM PK PA PN PE PH PW PG PL PR KP PT PY " +
  "PS PF QA RE RO RU RW SA SD SN SG GS SH SJ SB SL SV SM SO PM RS SS ST SR SK SI " +
  "SE SZ SX SC SY TC TD TG TH TJ TK TM TL TO TT TN TR TV TW TZ UG UA UM UY US UZ " +
  "VA VC VE VG VI VN VU WF WS YE ZA ZM ZW"
).split(" ");

export default function App() {
  const [tab, setTab] = useState<Tab>("upload");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [result, setResult] = useState<InvoiceUploadResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [progress, setProgress] = useState<ClassificationProgress | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [tradeMode, setTradeMode] = useState<TradeMode | "">("");
  const [originCountry, setOriginCountry] = useState("");
  const [dispatchCountry, setDispatchCountry] = useState("");

  // Re-render when language changes
  const [, setLangVersion] = useState(0);
  const currentLang: Lang = getLang();
  const dict = t();

  const countryOptions = useMemo(() => {
    const names = new Intl.DisplayNames([currentLang], { type: "region" });
    return COUNTRY_CODES
      .map((code) => ({ code, name: names.of(code) ?? code }))
      .sort((a, b) => a.name.localeCompare(b.name, currentLang));
  }, [currentLang]);

  const trade = useMemo<TradeDetails | null>(() => {
    if (!tradeMode || !originCountry || !dispatchCountry) return null;
    return {
      trade_mode: tradeMode,
      origin_country: originCountry,
      dispatch_country: dispatchCountry,
    };
  }, [dispatchCountry, originCountry, tradeMode]);

  useEffect(() => {
    let cancelled = false;
    fetchHealth()
      .then((h) => !cancelled && setHealth(h))
      .catch(() => !cancelled && setHealth(null));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!loading) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [loading]);

  function handleProgress(update: ClassificationProgress) {
    setProgress(update);
    if (update.invoice) {
      setResult(update.invoice);
      setWarning(update.invoice.warning ?? null);
    }
  }

  function resetTrade() {
    setTradeMode("");
    setOriginCountry("");
    setDispatchCountry("");
  }

  async function handleFile(file: File) {
    if (!trade) return;
    setError(null);
    setWarning(null);
    setResult(null);
    setElapsed(0);
    setProgress({ stage: "uploading", completed: 0, total: 0, invoice: null });
    setLoading(true);
    try {
      const res = await uploadInvoice(file, trade, handleProgress);
      setResult(res);
      resetTrade();
      if (res.warning) setWarning(res.warning);
    } catch (e) {
      setError(humanizeError(e));
      setProgress((current) => current ? { ...current, stage: "error" } : null);
    } finally {
      setLoading(false);
    }
  }

  async function handleText(text: string) {
    if (!trade) return;
    setError(null);
    setWarning(null);
    setResult(null);
    setElapsed(0);
    setProgress({ stage: "parsing", completed: 0, total: 0, invoice: null });
    setLoading(true);
    try {
      const res = await classifyRaw(text, trade, handleProgress);
      setResult(res);
      resetTrade();
      if (res.warning) setWarning(res.warning);
    } catch (e) {
      setError(humanizeError(e));
      setProgress((current) => current ? { ...current, stage: "error" } : null);
    } finally {
      setLoading(false);
    }
  }

  async function handleAnswer(index: number, answers: ClarificationAnswer[]) {
    if (!result || loading) throw new Error(dict.progress.stages.classifying);
    const invoice = result;
    const item = invoice.items[index];
    const response = await answerClarification(item.description, invoice.trade, answers);
    if (response.status === "error" || !response.result) {
      throw new Error(response.error ?? dict.errors.submit);
    }
    const previous = item.classification.result;
    if (previous) {
      response.result.prompt_tokens += previous.prompt_tokens;
      response.result.output_tokens += previous.output_tokens;
      response.result.total_tokens += previous.total_tokens;
    }
    setResult((current) => !current || current.items[index] !== item ? current : {
      ...current,
      items: current.items.map((entry, position) =>
        position === index ? { ...entry, classification: response } : entry),
    });
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

  const countryName = (code: string) =>
    countryOptions.find((country) => country.code === code)?.name ?? code;

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
          <fieldset disabled={loading} className="mb-6 rounded-xl border border-slate-200 p-4">
            <legend className="px-1 text-sm font-semibold text-slate-800">
              {dict.trade.title}
            </legend>
            <p className="mb-4 text-xs text-slate-500">{dict.trade.help}</p>
            <div className="grid gap-4 sm:grid-cols-3">
              <fieldset>
                <legend className="mb-2 text-xs font-medium text-slate-600">
                  {dict.trade.operation}
                </legend>
                <div className="flex gap-2">
                  {(["import", "export"] as const).map((mode) => (
                    <label
                      key={mode}
                      className={[
                        "flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm",
                        tradeMode === mode
                          ? "border-blue-500 bg-blue-50 text-blue-800"
                          : "border-slate-300 text-slate-600 hover:bg-slate-50",
                      ].join(" ")}
                    >
                      <input
                        type="radio"
                        name="trade_mode"
                        value={mode}
                        checked={tradeMode === mode}
                        onChange={() => setTradeMode(mode)}
                        required
                        className="h-4 w-4 border-slate-300 text-blue-600 focus:ring-blue-500"
                      />
                      {mode === "import" ? dict.trade.import : dict.trade.export}
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="block">
                <span className="mb-2 block text-xs font-medium text-slate-600">
                  {dict.trade.originCountry}
                </span>
                <select
                  required
                  value={originCountry}
                  onChange={(e) => setOriginCountry(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-200"
                >
                  <option value="">{dict.trade.selectCountry}</option>
                  {countryOptions.map((country) => (
                    <option key={country.code} value={country.code}>
                      {country.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-2 block text-xs font-medium text-slate-600">
                  {dict.trade.dispatchCountry}
                </span>
                <select
                  required
                  value={dispatchCountry}
                  onChange={(e) => setDispatchCountry(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-200"
                >
                  <option value="">{dict.trade.selectCountry}</option>
                  {countryOptions.map((country) => (
                    <option key={country.code} value={country.code}>
                      {country.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </fieldset>
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
            <InvoiceUpload
              loading={loading}
              canSubmit={trade !== null}
              onSubmit={handleFile}
            />
          ) : (
            <TextInput
              loading={loading}
              canSubmit={trade !== null}
              onSubmit={handleText}
            />
          )}
        </div>

        {progress && (
          <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div role="status" aria-live="polite">
                {dict.progress.stages[progress.stage]}
                {progress.total > 0 ? ` · ${dict.progress.count(progress.completed, progress.total)}` : ""}
              </div>
              <span>{dict.progress.elapsed(elapsed)}</span>
            </div>
            {progress.total > 0 && (
              <progress
                className="mt-2 h-2 w-full accent-blue-600"
                value={progress.completed}
                max={progress.total}
                aria-label={dict.progress.count(progress.completed, progress.total)}
              />
            )}
          </div>
        )}

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
            <div className="mb-3 flex flex-wrap gap-x-6 gap-y-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <span>
                <strong>{dict.trade.operation}:</strong>{" "}
                {result.trade.trade_mode === "import"
                  ? dict.trade.import
                  : dict.trade.export}
              </span>
              <span>
                <strong>{dict.trade.originCountry}:</strong>{" "}
                {countryName(result.trade.origin_country)}
              </span>
              <span>
                <strong>{dict.trade.dispatchCountry}:</strong>{" "}
                {countryName(result.trade.dispatch_country)}
              </span>
            </div>
            {(result.items.length > 0 || !loading) && (
              <ResultTable items={result.items} onAnswer={handleAnswer} disabled={loading} />
            )}
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
    if (e.status === 504) return dict.errors.timeout;
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
