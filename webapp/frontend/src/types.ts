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
  line_number?: number;
  description: string;
  classification: ClassifyResponse;
}

export type TradeMode = "import" | "export";

export interface TradeDetails {
  trade_mode: TradeMode;
  origin_country: string;
  dispatch_country: string;
}

export interface InvoiceUploadResponse {
  filename: string;
  source: "pdf" | "text" | "image" | "raw";
  pages?: number;
  items_count: number;
  items: InvoiceItem[];
  trade: TradeDetails;
  warning?: string;
}

export interface ClassificationProgress {
  stage: "uploading" | "parsing" | "classifying" | "done" | "error";
  completed: number;
  total: number;
  invoice: InvoiceUploadResponse | null;
}

export type ClassificationEvent =
  | { type: "stage"; stage: "parsing" }
  | { type: "ready"; invoice: InvoiceUploadResponse; total: number }
  | { type: "item"; index: number; item: InvoiceItem }
  | { type: "done" }
  | { type: "error"; status: number; message: string };

export interface HealthResponse {
  service: string;
  status: string;
  tariffai_url: string;
  tariffai_reachable: boolean;
}
