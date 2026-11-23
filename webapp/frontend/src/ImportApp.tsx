import { useEffect, useMemo, useRef, useState } from "react";
import { COUNTRY_CODES } from "./countries";
import { answerClarification, classifyRaw, extractImportFile, fetchEbtiEvidence, fetchImportQuestion, filterImportCandidates, lookupImportCase, storeImportCase, translateImportTexts, validateTaricCode } from "./api";
import type { ClarificationAnswer, ClassificationResult, ImportEvidenceItem, InvoiceItem, ImportQuestion, TradeDetails } from "./types";

type Lang = "es" | "en" | "fr" | "de" | "it";
const LANGS: Lang[] = ["es", "en", "fr", "de", "it"];
const COPY: Record<Lang, Record<string, string>> = {
  es: { title: "MyTarik · Importaciones", subtitle: "Describe el producto o sube el documento del cliente. La IA buscará el código TARIC y te preguntará solo lo necesario.", paste: "Producto o listado de productos", pasteHint: "Escribe un producto por línea. Ejemplo: tornillos de titanio", file: "Subir documento", addFile: "Añadir otro documento", classify: "Buscar códigos TARIC", operation: "Operación", import: "Importación", export: "Exportación", origin: "País de origen", dispatch: "País de expedición", questions: "Preguntas para afinar", answer: "Respuesta", send: "Enviar respuesta", candidates: "Candidatos TARIC", more: "Ampliar información", select: "Seleccionar este código", confirm: "Confirmar código", selected: "Código confirmado", manual: "Buscar código manualmente", manualHint: "8 o 10 dígitos", noCandidate: "No encontrado en TARIC", exportPdf: "Exportar PDF", result: "Resultados", pending: "Pendiente de confirmar", items: "artículos", error: "Error", processing: "Procesando…" },
  en: { title: "MyTarik · Imports", subtitle: "Describe the product or upload the customer document. AI will find the TARIC code and ask only what is needed.", paste: "Product or product list", pasteHint: "One product per line. Example: titanium screws", file: "Upload document", addFile: "Add another document", classify: "Find TARIC codes", operation: "Operation", import: "Import", export: "Export", origin: "Country of origin", dispatch: "Country of dispatch", questions: "Clarifying questions", answer: "Answer", send: "Send answer", candidates: "TARIC candidates", more: "More information", select: "Select this code", confirm: "Confirm code", selected: "Code confirmed", manual: "Search code manually", manualHint: "8 or 10 digits", noCandidate: "Not found in TARIC", exportPdf: "Export PDF", result: "Results", pending: "Pending confirmation", items: "items", error: "Error", processing: "Processing…" },
  fr: { title: "MyTarik · Importations", subtitle: "Décrivez le produit ou téléversez le document du client. L'IA cherchera le code TARIC et posera uniquement les questions nécessaires.", paste: "Produit ou liste de produits", pasteHint: "Un produit par ligne. Exemple : vis en titane", file: "Téléverser un document", addFile: "Ajouter un autre document", classify: "Chercher les codes TARIC", operation: "Opération", import: "Importation", export: "Exportation", origin: "Pays d'origine", dispatch: "Pays d'expédition", questions: "Questions de précision", answer: "Réponse", send: "Envoyer la réponse", candidates: "Candidats TARIC", more: "Plus d'informations", select: "Sélectionner ce code", confirm: "Confirmer le code", selected: "Code confirmé", manual: "Rechercher un code manuellement", manualHint: "8 ou 10 chiffres", noCandidate: "Non trouvé dans TARIC", exportPdf: "Exporter en PDF", result: "Résultats", pending: "En attente de confirmation", items: "articles", error: "Erreur", processing: "Traitement…" },
  de: { title: "MyTarik · Importe", subtitle: "Beschreiben Sie das Produkt oder laden Sie das Kundendokument hoch. Die KI sucht den TARIC-Code und fragt nur das Nötige.", paste: "Produkt oder Produktliste", pasteHint: "Ein Produkt pro Zeile. Beispiel: Titanschrauben", file: "Dokument hochladen", addFile: "Weiteres Dokument hinzufügen", classify: "TARIC-Codes suchen", operation: "Vorgang", import: "Import", export: "Export", origin: "Ursprungsland", dispatch: "Versandland", questions: "Präzisierungsfragen", answer: "Antwort", send: "Antwort senden", candidates: "TARIC-Kandidaten", more: "Weitere Informationen", select: "Diesen Code auswählen", confirm: "Code bestätigen", selected: "Code bestätigt", manual: "Code manuell suchen", manualHint: "8 oder 10 Ziffern", noCandidate: "Nicht in TARIC gefunden", exportPdf: "PDF exportieren", result: "Ergebnisse", pending: "Bestätigung ausstehend", items: "Artikel", error: "Fehler", processing: "Verarbeitung…" },
  it: { title: "MyTarik · Importazioni", subtitle: "Descrivi il prodotto o carica il documento del cliente. L'IA cercherà il codice TARIC e farà solo le domande necessarie.", paste: "Prodotto o elenco prodotti", pasteHint: "Un prodotto per riga. Esempio: viti di titanio", file: "Carica documento", addFile: "Aggiungi un altro documento", classify: "Cerca codici TARIC", operation: "Operazione", import: "Importazione", export: "Esportazione", origin: "Paese di origine", dispatch: "Paese di spedizione", questions: "Domande di chiarimento", answer: "Risposta", send: "Invia risposta", candidates: "Candidati TARIC", more: "Ulteriori informazioni", select: "Seleziona questo codice", confirm: "Conferma codice", selected: "Codice confermato", manual: "Cerca codice manualmente", manualHint: "8 o 10 cifre", noCandidate: "Non trovato in TARIC", exportPdf: "Esporta PDF", result: "Risultati", pending: "In attesa di conferma", items: "articoli", error: "Errore", processing: "Elaborazione…" },
};

type ItemState = InvoiceItem & { asked: number; selected?: string; confirmed?: boolean; memory?: { confirmations?: number; code?: string }; engineQuestion?: ImportQuestion | null; engineChecked?: boolean; askedQuestions?: string[] };

export default function ImportApp() {
  const [lang, setLang] = useState<Lang>("es");
  const [operation, setOperation] = useState<"import" | "export">("import");
  const [origin, setOrigin] = useState("");
  const [dispatch, setDispatch] = useState("");
  const [text, setText] = useState("");
  const [fileItems, setFileItems] = useState<string[]>([]);
  const [items, setItems] = useState<ItemState[]>([]);
  const [loading, setLoading] = useState(false);
  const [pendingOption, setPendingOption] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<{ item: ItemState; code: string } | null>(null);
  const [translations, setTranslations] = useState<Record<string, string>>({});
  const fileRef = useRef<HTMLInputElement>(null);
  const s = COPY[lang];
  const trade = useMemo<TradeDetails | null>(() => origin && dispatch ? { trade_mode: operation, origin_country: origin.toUpperCase(), dispatch_country: dispatch.toUpperCase() } : null, [operation, origin, dispatch]);
  const countryOptions = useMemo(() => {
    const names = new Intl.DisplayNames([lang], { type: "region" });
    return COUNTRY_CODES.map((code) => ({ code, name: names.of(code) ?? code })).sort((a, b) => a.name.localeCompare(b.name, lang));
  }, [lang]);

  useEffect(() => {
    if (!loading) { setElapsed(0); return; }
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function extract(file: File) {
    setError(null);
    setLoading(true);
    try {
      const result = await extractImportFile(file);
      setFileItems((current) => [...current, ...result.items.map((item) => item.description)].slice(0, 100));
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); setPendingOption(null); }
  }

  async function classify() {
    const manual = text.split("\n").map((line) => line.trim()).filter(Boolean);
    const descriptions = [...fileItems, ...manual].slice(0, 100);
    if (!trade || !descriptions.length) { setError("Selecciona origen y expedición, y añade al menos un producto."); return; }
    setLoading(true); setError(null); setItems([]);
    try {
      const lookups = await Promise.all(descriptions.map((d) => lookupImportCase(d, trade, lang)));
      const misses = descriptions.filter((_, i) => !lookups[i].hit);
      const response = misses.length ? await classifyRaw(misses.join("\n"), trade, undefined, lang) : null;
      let missIndex = 0;
      const next = descriptions.map((description, i) => {
        const hit = lookups[i];
        if (hit.hit && hit.code) {
          const synthetic: ClassificationResult = {
            input_text: description, cleaned_text: description, primary_code: hit.code,
            primary_description: hit.description ?? "", cn8: hit.code.slice(0, 8),
            taric10: hit.code, description: hit.description ?? "", alternatives: [],
            alternative_codes: [], confidence: 1, reasoning: {}, hierarchy: {},
            is_ambiguous: false, processing_time_ms: 0, prompt_tokens: 0, output_tokens: 0,
            total_tokens: 0, thinking: null, reasoning_triggers: [], clarification_question: null,
            clarification_answers: [], needs_human_review: false,
          } as unknown as ClassificationResult;
          return { description, classification: { status: "classified", result: synthetic, error: null }, asked: 0, askedQuestions: [], selected: hit.code, memory: { confirmations: hit.confirmations, code: hit.code } } as ItemState;
        }
        const item = response!.items[missIndex++];
        const autoCode = item.classification.result?.termbase_auto_code ?? null;
        return { ...item, description, asked: 0, askedQuestions: [], selected: autoCode } as ItemState;
      });
      setItems(next);
      loadTranslations(next);
      void checkQuestions(next).then(setItems);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }

  async function answer(index: number, question: ImportQuestion, value: string, optionCode?: string) {
    const item = items[index];
    if (!item || !trade || !value.trim()) return;
    setLoading(true);
    setPendingOption(value.trim());
    try {
      const previous = (item.classification.result?.clarification_answers ?? []);
      const answers: ClarificationAnswer[] = [...previous, { question: question.question, answer: value }];
      const response = await answerClarification(item.description, trade, answers, lang);
      const before: { code: string; description: string }[] = (item.classification.result?.alternatives ?? item.classification.result?.alternative_codes ?? []).map((c) => ({ code: c.code, description: c.description ?? "" }));
      let filtered: { code: string; description: string }[] = before;
      if (question.attribute && before.length) {
        try {
          filtered = (await filterImportCandidates(item.description, before, question.attribute, value, optionCode)).map((c) => ({ code: c.code, description: c.description ?? "" }));
        } catch { /* keep classifier candidates */ }
      }
      let nextResponse = response;
      if (filtered.length && response.result) {
        const alternatives = filtered.map((c) => ({ code: c.code, description: c.description ?? "" })) as typeof response.result.alternatives;
        const primary = filtered.length === 1 ? filtered[0].code : response.result.primary_code;
        nextResponse = { ...response, result: { ...response.result, primary_code: primary, alternatives, alternative_codes: alternatives ?? [] } };
      }
      const selected = filtered.length === 1 ? filtered[0].code : undefined;
      const updated = items.map((entry, i) => i === index ? { ...entry, classification: nextResponse, asked: entry.asked + 1, askedQuestions: [...(entry.askedQuestions ?? []), question.question], selected: selected ?? entry.selected, engineChecked: false, engineQuestion: null } : entry);
      setItems(updated);
      loadTranslations(updated);
      void checkQuestions(updated).then(setItems);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }
  function candidates(item: ItemState) {
    const result = item.classification.result;
    const all = result?.alternatives ?? result?.alternative_codes ?? [];
    if (result?.primary_code && !all.some((c) => c.code === result.primary_code)) {
      all.unshift({ code: result.primary_code, description: result.description ?? result.primary_description ?? "", cn8: result.cn8 ?? undefined, taric10: result.taric10 ?? undefined });
    }
    return all;
  }

  async function checkQuestions(nextItems: ItemState[]): Promise<ItemState[]> {
    return Promise.all(nextItems.map(async (item) => {
      const result = item.classification.result;
      const candidateList = (result?.alternatives ?? result?.alternative_codes ?? []).map((c) => ({ code: c.code, description: c.description }));
      if (!result || !candidateList.length) return { ...item, engineChecked: true, engineQuestion: null };
      try {
        const question = await fetchImportQuestion(item.description, candidateList, lang);
        if (question && lang !== "en" && question.options.length) {
          try {
            const translated = await translateImportTexts(question.options, lang);
            return { ...item, engineChecked: true, engineQuestion: { ...question, options: translated } };
          } catch { /* keep official options */ }
        }
        return { ...item, engineChecked: true, engineQuestion: question };
      } catch { return { ...item, engineChecked: true, engineQuestion: null }; }
    }));
  }

  function loadTranslations(nextItems: ItemState[]) {
    const texts = Array.from(new Set(nextItems.flatMap((item) => {
      const result = item.classification.result;
      return [
        result?.description ?? "",
        ...(result?.alternatives ?? result?.alternative_codes ?? []).map((candidate) => candidate.description ?? ""),
      ];
    }).filter((text) => text && !/^[ -]*$/.test(text) === false)));
    if (lang === "en" || !texts.length) return;
    void translateImportTexts(texts.slice(0, 100), lang).then((values) => {
      setTranslations((current) => {
        const next = { ...current };
        texts.slice(0, 100).forEach((text, index) => { next[text] = values[index] ?? text; });
        return next;
      });
    }).catch(() => {});
  }

  function select(index: number, code: string) {
    setItems((current) => current.map((item, i) => i === index ? { ...item, selected: code } : item));
    setModal(null);
  }

  async function confirm(index: number) {
    const current = items[index];
    if (!current?.selected || !trade) return;
    try {
      const memory = await storeImportCase(current.description, current.selected, trade, lang);
      setItems((list) => list.map((item, i) => i === index ? { ...item, confirmed: true, memory: { confirmations: memory.confirmations, code: current.selected } } : item));
    } catch (e) { setError(String(e)); }
    const audit = JSON.parse(localStorage.getItem("mytarik-import-audit") ?? "[]");
    audit.push({ at: new Date().toISOString(), description: current.description, code: current.selected, trade });
    localStorage.setItem("mytarik-import-audit", JSON.stringify(audit));
  }

  function printPdf() { window.print(); }

  return (
    <div className="min-h-full bg-slate-50">
      <header className="border-b border-slate-200 bg-white print:hidden">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-4">
          <div><h1 className="text-xl font-semibold text-slate-900">{s.title}</h1><p className="mt-1 max-w-2xl text-sm text-slate-500">{s.subtitle}</p></div>
          <div className="flex items-center gap-2">
            <select value={lang} onChange={(e) => setLang(e.target.value as Lang)} className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs">
              {LANGS.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
            </select>
            <button onClick={printPdf} className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs text-white">{s.exportPdf}</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-5 px-4 py-6 print:max-w-none print:p-0">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm print:hidden">
          <div className="mb-4 grid gap-4 sm:grid-cols-3">
            <label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-600">{s.operation}</span><select value={operation} onChange={(e) => setOperation(e.target.value as "import" | "export")} className="w-full rounded-lg border border-slate-300 px-3 py-2"><option value="import">{s.import}</option><option value="export">{s.export}</option></select></label>
            <label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-600">{s.origin}</span><select value={origin} onChange={(e) => setOrigin(e.target.value)} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2"><option value="">—</option>{countryOptions.map((country) => <option key={country.code} value={country.code}>{country.name} ({country.code})</option>)}</select></label>
            <label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-600">{s.dispatch}</span><select value={dispatch} onChange={(e) => setDispatch(e.target.value)} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2"><option value="">—</option>{countryOptions.map((country) => <option key={country.code} value={country.code}>{country.name} ({country.code})</option>)}</select></label>
          </div>
          <label className="mb-3 block text-sm"><span className="mb-1 block text-xs font-medium text-slate-600">{s.paste}</span><textarea value={text} onChange={(e) => setText(e.target.value)} rows={7} placeholder={s.pasteHint} className="w-full rounded-xl border border-slate-300 p-3 text-sm" /></label>
          <div className="flex flex-wrap items-center gap-2">
            <input ref={fileRef} type="file" accept=".pdf,.xlsx,.xls,.csv,.txt,.docx,.odt" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) void extract(f); e.target.value = ""; }} />
            <button onClick={() => fileRef.current?.click()} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">{s.file}</button>
            {fileItems.length > 0 && <button onClick={() => fileRef.current?.click()} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">{s.addFile}</button>}
            <span className="text-xs text-slate-500">{fileItems.length} {s.items}</span>
            <button onClick={() => void classify()} disabled={loading} className="ml-auto rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300">{loading ? "…" : s.classify}</button>
          </div>
          {fileItems.length > 0 && <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">{fileItems.slice(0,8).map((d) => <div key={d}>• {d}</div>)}{fileItems.length > 8 && <div>+ {fileItems.length - 8}</div>}</div>}
          {error && <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{s.error}: {error}</div>}
        </section>

        {items.length > 0 && <section className="space-y-4"><h2 className="text-lg font-semibold text-slate-900">{s.result} · {items.length} {s.items}</h2>
          {items.map((item, index) => {
            const result = item.classification.result;
            const rawQuestion = item.engineChecked ? item.engineQuestion : result?.clarification_question;
            const candidateQuestion: ImportQuestion | null = rawQuestion
              ? ("attribute" in rawQuestion ? rawQuestion as ImportQuestion : { question: rawQuestion.question, options: rawQuestion.options, attribute: "" })
              : null;
            const question = candidateQuestion && !(item.askedQuestions ?? []).includes(candidateQuestion.question) ? candidateQuestion : null;
            const options = candidates(item);
            return <article key={`${item.description}-${index}`} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-2"><div><span className="text-xs text-slate-400">#{index + 1}</span><h3 className="font-medium text-slate-900">{item.description}</h3></div><div className="flex gap-1"><span className={`rounded-full px-2 py-1 text-xs ${item.confirmed ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{item.confirmed ? s.selected : s.pending}</span>{item.memory && <span className="rounded-full bg-blue-50 px-2 py-1 text-xs text-blue-700">Caso previo ×{item.memory.confirmations ?? 1}</span>}</div></div>
              {question && item.asked < 3 && <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3"><p className="text-sm font-medium text-amber-900">{s.questions}</p><p className="mt-1 text-sm text-amber-900">{question.question}</p>{loading && <ProcessingDots elapsed={elapsed} />}<div className="mt-2 flex flex-wrap gap-2">{question.options.map((option, optionIndex) => { const selected = pendingOption?.trim().toLowerCase() === option.trim().toLowerCase(); return <button type="button" key={`${option}-${optionIndex}`} disabled={loading} aria-pressed={selected} onClick={() => void answer(index, question, option, question.option_codes?.[optionIndex])} className={["rounded-lg border px-3 py-1.5 text-xs disabled:opacity-50", selected ? "border-blue-600 bg-blue-100 font-medium text-blue-900" : "border-amber-300 bg-white hover:bg-amber-100"].join(" ")}>{selected && <span aria-hidden="true">✓ </span>}{option}</button>; })}</div><AnswerBox onSend={(value) => void answer(index, question, value)} placeholder={s.answer} send={s.send} loading={loading} /></div>}
              {(!question || item.asked >= 3) && <div className="mt-3 space-y-2">
                {options.length === 0 && <p className="text-sm text-rose-700">{s.noCandidate}</p>}
                {options.map((candidate) => <div key={candidate.code} className={`rounded-lg border p-2 ${item.selected === candidate.code ? "border-blue-500 bg-blue-50" : "border-slate-200"}`}><div className="flex flex-wrap items-center justify-between gap-2"><div><span className="font-mono text-sm font-semibold">{candidate.code}</span><span className="ml-2 text-xs text-slate-600">{translations[candidate.description ?? ""] ?? candidate.description}</span></div><div className="flex gap-2"><button onClick={() => setModal({ item, code: candidate.code })} className="text-xs font-semibold text-blue-700 underline">{s.more}</button><button onClick={() => select(index, candidate.code)} className="rounded bg-slate-800 px-2 py-1 text-xs text-white">{s.select}</button></div></div></div>)}
                {result?.termbase_matches?.length ? <div className="rounded-lg border border-blue-200 bg-blue-50 p-2"><p className="text-xs font-semibold text-blue-900">Base de términos comerciales</p><div className="mt-1 flex flex-wrap gap-2">{result.termbase_matches.map((match) => <button key={`${match.term}-${match.code}`} onClick={() => select(index, match.code)} className="rounded border border-blue-300 bg-white px-2 py-1 text-left text-xs hover:bg-blue-100"><span className="font-mono font-semibold">{match.code}</span><span className="ml-1 text-slate-600">{match.term}</span>{match.ebti?.length ? <span className="ml-1 text-blue-700">· {match.ebti.length} EBTI</span> : null}</button>)}</div></div> : null}
                <ManualCode label={s.manual} hint={s.manualHint} noCandidate={s.noCandidate} onSelect={(code) => select(index, code)} />
                {item.selected && <div className="flex flex-wrap items-center gap-2"><span className="text-xs text-slate-500">{s.manual}: <span className="font-mono">{item.selected}</span></span><button onClick={() => void confirm(index)} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs text-white">{s.confirm}</button></div>}
              </div>}
            </article>;
          })}
        </section>}
      </main>
      {modal && <InfoModal item={modal.item} code={modal.code} label={s.more} translations={translations} lang={lang} onClose={() => setModal(null)} />}
      {loading && <LoadingOverlay label={`${s.processing ?? "Procesando…"}${elapsed ? ` · ${elapsed} s` : ""}`} />}
    </div>
  );
}

function ProcessingDots({ elapsed = 0 }: { elapsed?: number }) {
  return <span className="inline-flex items-center gap-1 text-xs text-amber-800" role="status" aria-live="polite"><span className="h-3 w-3 animate-spin rounded-full border-2 border-amber-600 border-t-transparent" aria-hidden="true" /><span>La IA está pensando…</span>{elapsed > 0 && <span>· {elapsed} s</span>}</span>;
}

function AnswerBox({ onSend, placeholder, send, loading }: { onSend: (value: string) => void; placeholder: string; send: string; loading?: boolean }) {
  const [value, setValue] = useState("");
  return <div className="mt-2 flex gap-2"><input value={value} disabled={loading} onChange={(e) => setValue(e.target.value)} placeholder={placeholder} className="min-w-0 flex-1 rounded-lg border border-amber-300 bg-white px-2 py-1 text-sm" /><button disabled={loading} onClick={() => { onSend(value); setValue(""); }} className="rounded-lg bg-amber-700 px-2 py-1 text-xs text-white disabled:opacity-50">{send}</button></div>;
}

function ManualCode({ label, hint, noCandidate, onSelect }: { label: string; hint: string; noCandidate: string; onSelect: (code: string) => void }) {
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function check() {
    setBusy(true); setStatus(null);
    try {
      const result = await validateTaricCode(code);
      if (!result.valid) { setStatus(result.error ?? noCandidate); return; }
      setStatus(result.description ?? "Código validado");
      onSelect(result.taric10 ?? result.cn8 ?? code);
    } catch (e) { setStatus(String(e)); }
    finally { setBusy(false); }
  }
  return <div className="mt-3 rounded-lg border border-dashed border-slate-300 p-2">
    <div className="flex flex-wrap items-center gap-2">
      <input value={code} onChange={(e) => setCode(e.target.value)} placeholder={`${label} · ${hint}`} className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 font-mono text-xs" />
      <button onClick={() => void check()} disabled={busy || !code.trim()} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700 disabled:opacity-50">{busy ? "…" : label}</button>
    </div>
    {status && <p className="mt-1 text-xs text-slate-600">{status}</p>}
  </div>;
}

function InfoModal({ item, code, label, translations, lang, onClose }: { item: ItemState; code: string; label: string; translations: Record<string, string>; lang: Lang; onClose: () => void }) {
  const result = item.classification.result;
  const candidate = (result?.alternatives ?? result?.alternative_codes ?? []).find((c) => c.code === code);
  const [evidence, setEvidence] = useState<ImportEvidenceItem[]>([]);
  const [evidenceTranslations, setEvidenceTranslations] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchEbtiEvidence(code)
      .then(async (response) => {
        if (cancelled) return;
        setEvidence(response.evidence);
        const texts = Array.from(new Set(response.evidence.flatMap((entry) => [entry.description, entry.justification ?? ""]).filter(Boolean)));
        if (lang !== "en" && texts.length) {
          try {
            const values = await translateImportTexts(texts, lang);
            if (cancelled) return;
            const map: Record<string, string> = {};
            texts.forEach((text, index) => { map[text] = values[index] ?? text; });
            setEvidenceTranslations(map);
          } catch { /* keep original */ }
        }
      })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [code, lang]);
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}><div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
    <div className="flex items-center justify-between"><h3 className="text-lg font-semibold">{label} · {code}</h3><button onClick={onClose} className="text-slate-500">×</button></div>
    {candidate?.description && <p className="mt-2 text-sm text-slate-700">{translations[candidate.description] ?? candidate.description}</p>}
    <p className="mt-3 text-sm"><b>Confianza:</b> {Math.round((result?.confidence ?? 0) * 100)}%</p>
    <p className="mt-2 text-sm"><b>Motivo:</b> {result?.reasoning?.heading_reasoning ?? result?.reasoning?.subheading_reasoning ?? "No disponible"}</p>
    <h4 className="mt-4 text-sm font-semibold text-slate-900">Evidencia EBTI</h4>
    {loading && <p className="text-xs text-slate-500">Consultando EBTI…</p>}
    {error && <p className="text-xs text-rose-600">No se pudo consultar EBTI: {error}</p>}
    {!loading && !error && evidence.length === 0 && <p className="text-xs text-slate-500">No hay decisiones EBTI para este código.</p>}
    <div className="mt-2 space-y-2">{evidence.map((entry, i) => <div key={`${entry.reference}-${i}`} className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs">
      <div className="flex flex-wrap justify-between gap-1"><span className="font-mono font-semibold">{entry.reference ?? "EBTI"}</span><span className="text-slate-500">{entry.country} {entry.start_date}</span></div>
      <p className="mt-1 text-slate-800">{evidenceTranslations[entry.description] ?? entry.description}</p>
      {entry.justification && <p className="mt-1 line-clamp-3 text-slate-500">{evidenceTranslations[entry.justification] ?? entry.justification}</p>}
    </div>)}</div>
  </div></div>;
}


function LoadingOverlay({ label }: { label: string }) {
  return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/20 backdrop-blur-[1px]" role="status" aria-live="polite">
    <div className="flex flex-col items-center gap-4 rounded-2xl bg-white px-8 py-6 shadow-xl">
      <span className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-blue-600" />
      <div className="flex items-center gap-1.5 text-sm font-medium text-slate-700">
        {label}
        <span className="flex gap-1"><span className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-600" /><span className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-600 [animation-delay:150ms]" /><span className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-600 [animation-delay:300ms]" /></span>
      </div>
    </div>
  </div>;
}
