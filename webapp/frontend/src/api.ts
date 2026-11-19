import type {
  ClassificationEvent, ClassificationProgress, HealthResponse, InvoiceItem,
  ImportExtractResponse, ImportEvidenceResponse, ImportValidateResponse, ImportCaseLookup, ImportQuestion,
  InvoiceUploadResponse, TradeDetails,
  ClarificationAnswer, ClassifyResponse,
  CustomsOperationRequest, CustomsOperationResponse,
  ResolveTaricCodesResponse, HS6LookupResponse,
} from "./types";
import { getLang } from "./i18n/strings";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function safeText(res: Response): Promise<string> {
  try {
    return await res.text();
  } catch {
    return "";
  }
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await safeText(res);
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export function isValidTradeDetails(value: unknown): value is TradeDetails {
  if (!value || typeof value !== "object") return false;
  const trade = value as Partial<TradeDetails>;
  return (
    (trade.trade_mode === "import" || trade.trade_mode === "export") &&
    typeof trade.origin_country === "string" &&
    /^[A-Z]{2}$/.test(trade.origin_country) &&
    typeof trade.dispatch_country === "string" &&
    /^[A-Z]{2}$/.test(trade.dispatch_country)
  );
}

export async function uploadInvoice(
  file: File,
  trade: TradeDetails,
  onProgress?: (progress: ClassificationProgress) => void,
): Promise<InvoiceUploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("language", getLang());
  fd.append("trade_mode", trade.trade_mode);
  fd.append("origin_country", trade.origin_country);
  fd.append("dispatch_country", trade.dispatch_country);
  const res = await fetch("/api/invoice/upload", {
    method: "POST",
    headers: onProgress ? { accept: "application/x-ndjson" } : undefined,
    body: fd,
  });
  if (onProgress) return readProgress(res, onProgress);
  return jsonOrThrow<InvoiceUploadResponse>(res);
}

export async function extractImportFile(file: File): Promise<ImportExtractResponse> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/import/extract", { method: "POST", body: fd });
  return jsonOrThrow<ImportExtractResponse>(res);
}

export async function classifyRaw(
  text: string,
  trade: TradeDetails,
  onProgress?: (progress: ClassificationProgress) => void,
  language: string = getLang(),
): Promise<InvoiceUploadResponse> {
  const res = await fetch("/api/classify/raw", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(onProgress ? { accept: "application/x-ndjson" } : {}),
    },
    body: JSON.stringify({ text, language, trade }),
  });
  if (onProgress) return readProgress(res, onProgress);
  return jsonOrThrow<InvoiceUploadResponse>(res);
}

export async function answerClarification(
  description: string,
  trade: TradeDetails,
  clarificationAnswers: ClarificationAnswer[],
  language: string = getLang(),
): Promise<ClassifyResponse> {
  const res = await fetch("/api/classify", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      description, trade, language, clarification_answers: clarificationAnswers,
    }),
  });
  return jsonOrThrow<ClassifyResponse>(res);
}

async function readProgress(
  res: Response, onProgress: (progress: ClassificationProgress) => void,
): Promise<InvoiceUploadResponse> {
  if (!res.ok) return jsonOrThrow<InvoiceUploadResponse>(res);
  if (!res.body || !res.headers.get("content-type")?.includes("application/x-ndjson")) {
    throw new ApiError(502, "Invalid classification stream");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const items = new Map<number, InvoiceItem>();
  let invoice: InvoiceUploadResponse | null = null;
  let total = 0;
  let finished = false;
  let buffer = "";

  function consume(line: string) {
    if (!line.trim()) return;
    const event = JSON.parse(line) as ClassificationEvent;
    if (!event || typeof event !== "object") throw new ApiError(502, "Invalid progress event");
    switch (event.type) {
      case "stage":
        onProgress({ stage: "parsing", completed: 0, total: 0, invoice: null });
        break;
      case "ready":
        if (invoice || !Number.isInteger(event.total) || event.total < 0
            || !event.invoice || !Array.isArray(event.invoice.items)
            || !isValidTradeDetails(event.invoice.trade)) {
          throw new ApiError(502, "Invalid classification metadata");
        }
        total = event.total;
        invoice = event.invoice;
        onProgress({ stage: "classifying", completed: 0, total, invoice });
        break;
      case "item":
        if (!invoice || !Number.isInteger(event.index) || event.index < 0
            || event.index >= total || items.has(event.index) || !event.item?.classification) {
          throw new ApiError(502, "Invalid classification item");
        }
        items.set(event.index, event.item);
        invoice = {
          ...invoice,
          items_count: items.size,
          items: [...items.entries()].sort(([a], [b]) => a - b).map(([, item]) => item),
        };
        onProgress({ stage: "classifying", completed: items.size, total, invoice });
        break;
      case "done":
        if (!invoice || items.size !== total) throw new ApiError(502, "Incomplete classification stream");
        finished = true;
        onProgress({ stage: "done", completed: items.size, total, invoice });
        break;
      case "error":
        throw new ApiError(event.status, event.message);
      default:
        throw new ApiError(502, "Unknown classification progress event");
    }
  }

  try {
    while (!finished) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let newline: number;
      while (!finished && (newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        consume(line);
      }
      if (done) {
        if (!finished && buffer.trim()) consume(buffer);
        break;
      }
    }
    if (!finished || !invoice) throw new ApiError(502, "Incomplete classification stream");
    return invoice;
  } finally {
    try {
      await reader.cancel();
    } finally {
      reader.releaseLock();
    }
  }
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch("/api/health");
  return jsonOrThrow<HealthResponse>(res);
}

export async function evaluateCustomsOperation(
  request: Omit<CustomsOperationRequest, "language">,
): Promise<CustomsOperationResponse> {
  const res = await fetch("/api/v1/customs/evaluate-operation", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ ...request, language: getLang() }),
  });
  return jsonOrThrow<CustomsOperationResponse>(res);
}

export async function resolveTaricCodes(
  hsCode: string,
  country: string,
): Promise<ResolveTaricCodesResponse> {
  const res = await fetch("/api/v1/customs/resolve-taric-codes", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ hs_code: hsCode, country, language: getLang() }),
  });
  return jsonOrThrow<ResolveTaricCodesResponse>(res);
}

export async function hs6Lookup(query: string, topK: number = 5): Promise<HS6LookupResponse> {
  const res = await fetch("/api/reference/hs6", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query, top_k: topK }),
  });
  return jsonOrThrow<HS6LookupResponse>(res);
}

export async function fetchEbtiEvidence(code: string): Promise<ImportEvidenceResponse> {
  const res = await fetch(`/api/import/evidence?code=${encodeURIComponent(code)}`);
  return jsonOrThrow<ImportEvidenceResponse>(res);
}

export async function validateTaricCode(code: string): Promise<ImportValidateResponse> {
  const res = await fetch("/api/import/validate", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ code }),
  });
  return jsonOrThrow<ImportValidateResponse>(res);
}

export async function lookupImportCase(description: string, trade: TradeDetails, language: string): Promise<ImportCaseLookup> {
  const res = await fetch("/api/import/cases/lookup", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ description, trade, language, taric_version: "2026-11" }),
  });
  return jsonOrThrow<ImportCaseLookup>(res);
}

export async function storeImportCase(description: string, code: string, trade: TradeDetails, language: string): Promise<ImportCaseLookup> {
  const res = await fetch("/api/import/cases/confirm", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ description, code, trade, language, taric_version: "2026-11" }),
  });
  return jsonOrThrow<ImportCaseLookup>(res);
}

export async function fetchImportQuestion(description: string, candidates: { code: string; description?: string }[], language: string): Promise<ImportQuestion | null> {
  const res = await fetch("/api/import/questions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ description, candidates, language }),
  });
  const data = await jsonOrThrow<{ question: ImportQuestion | null }>(res);
  return data.question;
}

export async function filterImportCandidates(description: string, candidates: { code: string; description?: string }[], attribute: string, answer: string, optionCode?: string): Promise<{ code: string; description?: string }[]> {
  const res = await fetch("/api/import/filter", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ description, candidates, attribute, answer, option_code: optionCode }),
  });
  const data = await jsonOrThrow<{ candidates: { code: string; description?: string }[] }>(res);
  return data.candidates;
}

export async function translateImportTexts(texts: string[], targetLanguage: string): Promise<string[]> {
  if (!texts.length || targetLanguage === "en") return texts;
  const res = await fetch("/api/import/translate", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ texts, target_language: targetLanguage }),
  });
  const data = await jsonOrThrow<{ translations: string[] }>(res);
  return data.translations;
}
