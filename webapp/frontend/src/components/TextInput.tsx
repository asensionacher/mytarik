import { useState } from "react";
import { t } from "../i18n/strings";

interface Props {
  loading: boolean;
  onSubmit: (text: string) => void;
}

export function TextInput({ loading, onSubmit }: Props) {
  const s = t().paste;
  const [text, setText] = useState("");

  return (
    <div className="space-y-4">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={s.placeholder}
        rows={12}
        className="block w-full resize-y rounded-xl border border-slate-300 bg-white p-4 font-mono text-sm shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-200"
      />
      <button
        type="button"
        disabled={!text.trim() || loading}
        onClick={() => onSubmit(text)}
        className={[
          "w-full rounded-xl px-4 py-3 text-base font-medium text-white shadow-sm transition-colors",
          !text.trim() || loading
            ? "bg-slate-300 cursor-not-allowed"
            : "bg-blue-600 hover:bg-blue-700",
        ].join(" ")}
      >
        {loading ? s.submitting : s.submit}
      </button>
    </div>
  );
}
