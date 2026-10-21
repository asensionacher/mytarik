/**
 * strings.ts — textos de la UI organizados por idioma.
 *
 * Estructura lista para i18n: añadir un nuevo idioma es crear la entrada en
 * `dict` siguiendo la forma de `dict.es`. El cast final garantiza que todas
 * las traducciones tengan la misma forma en compile-time.
 */

// `dict` se declara con `satisfies` para forzar que ambos idiomas tengan
// la misma forma (mismas claves, mismos tipos). El tipo se deriva del español
// y se aplica al inglés al final, no al revés.
export const dict = {
  es: {
    appTitle: "MyTarik · Clasificador HS",
    appSubtitle:
      "Sube una factura o pega su texto; te sugerimos códigos HS con la cadena de razonamiento.",
    model: {
      label: "Modelo LLM",
      help: "Modelo concreto del proveedor elegido.",
      options: {
        "gemini-3.8-flash": "Gemini 3.8 Flash · recomendado",
        "gemini-3.6-flash": "Gemini 3.6 Flash",
        "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite",
        "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite",
        "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview",
        "gemini-3-flash-preview": "Gemini 3 Flash Preview",
        "MiniMax-M3.1-Flash": "MiniMax-M3.1-Flash",
      },
      placeholder: "(usar default)",
      defaultFromEnv: "(usar default)",
      custom: "(personalizado)",
    },
    provider: {
      label: "Proveedor",
      help: "Servicio LLM que ejecutará el modelo.",
      options: {
        minimax: "MiniMax",
        gemini: "Google Gemini",
      },
    },
    detail: {
      thinking: "Razonamiento interno del modelo",
      thinkingEmpty: "El modelo no expuso su razonamiento interno.",
    },
    tariffaiStatusLabel: "TariffAI",
    tariffaiOk: "conectado",
    tariffaiKo: "no responde",
    tabs: { upload: "Subir factura", paste: "Pegar texto" },
    upload: {
      dropHere: "Arrastra una factura aquí",
      orClick: "o haz clic para seleccionar",
      formats: "PDF, texto plano o imagen (jpg, png, webp)",
      maxSize: "Máx. 20 MB",
      selected: "Fichero seleccionado",
      change: "Cambiar",
      submit: "Clasificar factura",
      submitting: "Clasificando…",
    },
    paste: {
      placeholder:
        "Pega aquí el contenido de la factura, una descripción por línea…",
      submit: "Clasificar texto",
      submitting: "Clasificando…",
    },
    results: {
      title: "Resultados",
      noneFound: "No se detectaron líneas con descripción de producto.",
      warning: "Aviso",
      columns: {
        n: "#",
        desc: "Descripción original",
        code: "Código HS",
        hsDesc: "Descripción HS",
        conf: "Confianza",
        status: "Estado",
        expand: "Detalle",
      },
      status: {
        classified: "Clasificado",
        ambiguous: "Ambiguo",
        error: "Error",
      },
      itemsCount: (n: number) =>
        `${n} ${n === 1 ? "línea procesada" : "líneas procesadas"}`,
      tokensBadge: (n: number) => `${n.toLocaleString("es-ES")} tokens`,
    },
    details: {
      cleaned: "Texto limpiado",
      hierarchy: "Jerarquía",
      hierarchyLevels: {
        section: "Sección",
        chapter: "Capítulo",
        heading: "Partida",
        subheading: "Subpartida",
      },
      reasoning: "Razonamiento",
      reasoningLevels: {
        section: "Sección",
        chapter: "Capítulo",
        heading: "Partida",
        subheading: "Subpartida",
      },
      keyFactors: "Factores clave",
      alternatives: "Códigos alternativos",
      whyNot: "Por qué no",
      tradeOff: "Trade-off",
      time: (ms: number) => `Tiempo de procesamiento: ${ms.toFixed(0)} ms`,
    },
    tokens: {
      title: "Tokens consumidos",
      prompt: "Entrada (prompt)",
      output: "Salida (respuesta)",
      total: "Total",
      totalLabel: (n: number) => `${n.toLocaleString("es-ES")} tokens en total`,
      promptLabel: (n: number) => `${n.toLocaleString("es-ES")} ↑`,
      outputLabel: (n: number) => `${n.toLocaleString("es-ES")} ↓`,
      notReported: "n/d",
    },
    errors: {
      submit: "Ha habido un error al clasificar",
      empty: "El fichero está vacío",
      tooBig: "El fichero supera el tamaño máximo",
      format: "Formato no soportado",
      noApi: "No se pudo contactar con el backend",
      network: "Error de red",
    },
  },

  en: {
    appTitle: "MyTarik · HS classifier",
    appSubtitle:
      "Upload an invoice or paste its text; we suggest HS codes with a reasoning chain.",
    model: {
      label: "LLM model",
      help: "Concrete model for the selected provider.",
      options: {
        "gemini-3.8-flash": "Gemini 3.8 Flash · recommended",
        "gemini-3.6-flash": "Gemini 3.6 Flash",
        "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite",
        "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite",
        "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview",
        "gemini-3-flash-preview": "Gemini 3 Flash Preview",
        "MiniMax-M3.1-Flash": "MiniMax-M3.1-Flash",
      },
      placeholder: "(use default)",
      defaultFromEnv: "(use default)",
      custom: "(custom)",
    },
    provider: {
      label: "Provider",
      help: "LLM service that will execute the model.",
      options: {
        minimax: "MiniMax",
        gemini: "Google Gemini",
      },
    },
    detail: {
      thinking: "Model's internal reasoning",
      thinkingEmpty: "The model did not expose its internal reasoning.",
    },
    tariffaiStatusLabel: "TariffAI",
    tariffaiOk: "connected",
    tariffaiKo: "unreachable",
    tabs: { upload: "Upload invoice", paste: "Paste text" },
    upload: {
      dropHere: "Drop an invoice here",
      orClick: "or click to select",
      formats: "PDF, plain text or image (jpg, png, webp)",
      maxSize: "Max. 20 MB",
      selected: "Selected file",
      change: "Change",
      submit: "Classify invoice",
      submitting: "Classifying…",
    },
    paste: {
      placeholder:
        "Paste the invoice content here, one description per line…",
      submit: "Classify text",
      submitting: "Classifying…",
    },
    results: {
      title: "Results",
      noneFound: "No product description lines detected.",
      warning: "Warning",
      columns: {
        n: "#",
        desc: "Original description",
        code: "HS code",
        hsDesc: "HS description",
        conf: "Confidence",
        status: "Status",
        expand: "Detail",
      },
      status: {
        classified: "Classified",
        ambiguous: "Ambiguous",
        error: "Error",
      },
      itemsCount: (n: number) =>
        `${n} ${n === 1 ? "line processed" : "lines processed"}`,
      tokensBadge: (n: number) => `${n.toLocaleString("en-US")} tokens`,
    },
    details: {
      cleaned: "Cleaned text",
      hierarchy: "Hierarchy",
      hierarchyLevels: {
        section: "Section",
        chapter: "Chapter",
        heading: "Heading",
        subheading: "Subheading",
      },
      reasoning: "Reasoning",
      reasoningLevels: {
        section: "Section",
        chapter: "Chapter",
        heading: "Heading",
        subheading: "Subheading",
      },
      keyFactors: "Key factors",
      alternatives: "Alternative codes",
      whyNot: "Why not",
      tradeOff: "Trade-off",
      time: (ms: number) => `Processing time: ${ms.toFixed(0)} ms`,
    },
    tokens: {
      title: "Tokens used",
      prompt: "Prompt (input)",
      output: "Output (response)",
      total: "Total",
      totalLabel: (n: number) => `${n.toLocaleString("en-US")} tokens in total`,
      promptLabel: (n: number) => `${n.toLocaleString("en-US")} in`,
      outputLabel: (n: number) => `${n.toLocaleString("en-US")} out`,
      notReported: "n/a",
    },
    errors: {
      submit: "An error happened while classifying",
      empty: "The file is empty",
      tooBig: "The file exceeds the maximum size",
      format: "Unsupported format",
      noApi: "Could not reach the backend",
      network: "Network error",
    },
  },
};

// Tipo derivado del español: cualquier idioma nuevo debe satisfacer este shape.
// (Útil como referencia; no impone runtime checks.)
export type DictShape = typeof dict.es;

export type Lang = keyof typeof dict;
export const SUPPORTED_LANGS: Lang[] = ["es", "en"];

let current: Lang =
  (typeof navigator !== "undefined" &&
    (navigator.language?.toLowerCase().startsWith("en") ? "en" : "es")) ||
  "es";

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang): void {
  if (lang in dict) current = lang;
}

export function t() {
  return dict[current];
}
