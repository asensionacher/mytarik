import { ApiError } from "./api";
import { t } from "./i18n/strings";

/**
 * Traduce un error de la API a un mensaje comprensible para el usuario.
 */
export function humanizeError(e: unknown): string {
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
