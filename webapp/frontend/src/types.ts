// Mirror de la respuesta del backend para tener tipado fuerte en el cliente.

export interface ClassificationReasoning {
  section_reasoning: string;
  chapter_reasoning: string;
  heading_reasoning: string;
  subheading_reasoning: string;
  key_factors: string[];
}

export interface AlternativeCode {
  code: string;
  description: string;
  why_not?: string | null;
  trade_off?: string | null;
}

export interface HierarchyEntry {
  code: string;
  description: string;
}

export interface Hierarchy {
  section?: HierarchyEntry;
  chapter?: HierarchyEntry;
  heading?: HierarchyEntry;
  subheading?: HierarchyEntry;
  [k: string]: HierarchyEntry | undefined;
}

export interface ClassificationResult {
  input_text: string;
  cleaned_text: string;
  primary_code: string | null;
  primary_description: string | null;
  confidence: number;
  reasoning: ClassificationReasoning;
  hierarchy: Hierarchy;
  alternative_codes: AlternativeCode[];
  is_ambiguous: boolean;
  processing_time_ms: number;
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
  thinking: string | null;
}

export type ClassifyStatus = "classified" | "ambiguous" | "error";

export interface ClassifyResponse {
  status: ClassifyStatus;
  result: ClassificationResult | null;
  error: string | null;
}

export interface InvoiceItem {
  description: string;
  classification: ClassifyResponse;
}

export interface InvoiceUploadResponse {
  filename: string;
  source: "pdf" | "text" | "image";
  pages?: number;
  items_count: number;
  items: InvoiceItem[];
  warning?: string;
}

export interface HealthResponse {
  service: string;
  status: string;
  tariffai_url: string;
  tariffai_reachable: boolean;
}
