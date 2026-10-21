import type {
  ClassificationEvent, ClassificationProgress, HealthResponse, InvoiceItem,
  InvoiceUploadResponse,
} from "./types";

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

export async function uploadInvoice(
  file: File,
  onProgress?: (progress: ClassificationProgress) => void,
): Promise<InvoiceUploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/invoice/upload", {
    method: "POST",
    headers: onProgress ? { accept: "application/x-ndjson" } : undefined,
    body: fd,
  });
  if (onProgress) return readProgress(res, onProgress);
  return jsonOrThrow<InvoiceUploadResponse>(res);
}

export async function classifyRaw(
  text: string,
  onProgress?: (progress: ClassificationProgress) => void,
): Promise<InvoiceUploadResponse> {
  const res = await fetch("/api/classify/raw", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(onProgress ? { accept: "application/x-ndjson" } : {}),
    },
    body: JSON.stringify({ text }),
  });
  if (onProgress) return readProgress(res, onProgress);
  return jsonOrThrow<InvoiceUploadResponse>(res);
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
            || !event.invoice || !Array.isArray(event.invoice.items)) {
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
