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
  reasoning_triggers: string[];
  clarification_question: { question: string; options: string[] } | null;
  clarification_answers: ClarificationAnswer[];
  needs_human_review: boolean;
}

export interface ClarificationAnswer {
  question: string;
  answer: string;
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

// ── Motor de medidas aduaneras ─────────────────────────────────────────

export type CustomsOperationType = "IMPORT" | "EXPORT";

export type CustomsRegime =
  | "INTRA_UNION"
  | "INTRA_UNION_TERRITORIAL_EXCEPTION"
  | "IMPORT_FROM_THIRD_COUNTRY"
  | "EXPORT_TO_THIRD_COUNTRY";

export type ReportingRequirement =
  | "INTRSTAT"
  | "VAT_INTRA_COMMUNITY"
  | "VAT_IMPORT"
  | "IGIC"
  | "AIEM"
  | "AX_VAT"
  | "CUSTOMS_DECLARATION"
  | "EXPORT_DECLARATION";

export interface CustomsItem {
  taric_code: string;
  description: string;
  customs_value?: number | null;
  currency?: string | null;
  net_weight_kg?: number | null;
  supplementary_units?: number | null;
}

export interface CustomsOperationRequest {
  operation_type: CustomsOperationType;
  origin_country: string;
  destination_country: string;
  incoterm?: string | null;
  language: "es" | "en";
  origin_subdivision?: string | null;
  destination_subdivision?: string | null;
  items: CustomsItem[];
}

export interface DutyRate {
  kind: "ad_valorem" | "specific" | "compound" | "unknown";
  ad_valorem_percent: number | null;
  specific_amount: number | null;
  specific_currency: string | null;
  specific_unit: string | null;
  formula_raw: string;
}

export interface MeasureFootnote {
  code: string;
  type: string;
  text: string;
}

export interface MeasureCondition {
  sequence_number: string;
  description: string;
  action_description: string;
  certificate_type: string | null;
  certificate_number: string | null;
  certificate_description: string;
  condition_expression: string | null;
  tariff_formula: string | null;
}

export interface DutyMeasure {
  measure_type: string;
  measure_type_label: string;
  category: string;
  origin: string;
  geographic_area: string;
  description: string;
  duty: DutyRate;
  valid_from: string | null;
  valid_to: string | null;
  regulation_id: string | null;
  exclusions: string | null;
  footnotes: MeasureFootnote[];
  conditions: MeasureCondition[];
}

export interface ThirdCountryDuty extends DutyMeasure {
  variants: DutyMeasure[];
}

export interface PreferentialDuty extends DutyMeasure {
  agreement: string;
  proof_of_origin: string[];
}

export interface TradeDefenseMeasure extends DutyMeasure {
  defense_kind: "ANTI_DUMPING" | "COUNTERVAILING" | "SAFEGUARD";
  additional_code: string | null;
  additional_code_text: string | null;
  certificate_code: string | null;
  certificate_description: string;
  residual_duty: DutyRate | null;
  proof_of_origin: string[];
}

export interface BorderControl {
  category: "SPS" | "TBT" | "DOCUMENT" | "INSPECTION" | "CUSTOMS_CONTROL";
  code: string;
  title: string;
  authority: string | null;
  requirement: string;
  mandatory: boolean;
  source: string;
}

export interface SpecialRegulation {
  regulation: string;
  name: string;
  applies: boolean;
  reference: string | null;
  reason: string;
  action_required: string | null;
  source: string;
}

export interface ExemptionCode {
  code: string;
  description: string;
  applies_to: string;
  action: string;
}

export interface TaxEstimation {
  currency: string;
  customs_value: number;
  estimated_duty: number;
  duty_breakdown: string[];
  estimated_vat_base: number;
  estimated_vat_rate: number | null;
  estimated_vat: number | null;
  incoterm_adjustment: string | null;
  formula: string;
  notes: string[];
}

export interface ExecutiveSummary {
  duty_to_pay: string;
  how_to_reduce_to_zero: string | null;
  border_controls: string[];
  special_regulations: string[];
  y_codes_to_declare: string[];
  warnings: string[];
  needs_human_review: boolean;
}

export interface ItemProvenance {
  provider: string;
  source: string;
  cache_hit: boolean;
  queried_code: string | null;
  raw_measure_count: number;
  fetched_at: string | null;
  warnings: string[];
}

export interface ItemMeasures {
  line_number: number;
  taric_code: string;
  description: string;
  product_description: string | null;
  third_country_duty: ThirdCountryDuty | null;
  preferential_duties: PreferentialDuty[];
  trade_defense_measures: TradeDefenseMeasure[];
  border_controls_and_inspections: BorderControl[];
  environmental_and_special_regulations: SpecialRegulation[];
  exemption_y_codes: ExemptionCode[];
  tax_estimation: TaxEstimation | null;
  executive_summary: ExecutiveSummary | null;
  provenance: ItemProvenance;
}

export interface CustomsOperationResponse {
  status: "ok" | "partial" | "error";
  operation_type: CustomsOperationType;
  origin_country: string;
  destination_country: string;
  incoterm: string | null;
  customs_regime: CustomsRegime;
  territorial_note: string | null;
  reporting_requirements: ReportingRequirement[];
  items_measures: ItemMeasures[];
  warnings: string[];
  provider: string;
  cache_hits: number;
  processing_time_ms: number;
  error: string | null;
}
