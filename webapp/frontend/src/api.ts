import type { HealthResponse, InvoiceUploadResponse } from "./types";

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
): Promise<InvoiceUploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/invoice/upload", {
    method: "POST",
    body: fd,
  });
  return jsonOrThrow<InvoiceUploadResponse>(res);
}

export async function classifyRaw(
  text: string,
): Promise<InvoiceUploadResponse> {
  const res = await fetch("/api/classify/raw", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return jsonOrThrow<InvoiceUploadResponse>(res);
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch("/api/health");
  return jsonOrThrow<HealthResponse>(res);
}
