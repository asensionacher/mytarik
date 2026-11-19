#!/usr/bin/env python3
"""Train a multilingual cross-encoder reranker from EBTI + TARIC tree.

Positive: EBTI description ↔ official description of its code.
Hard negative: a sibling under the same parent.
Random negative: another TARIC leaf.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREE = ROOT / "taric_tree.json"
DEFAULT_DATA = ROOT / "data" / "real" / "ebti_labels.jsonl"
DEFAULT_OUT = ROOT / "models" / "reranker"


def digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))[:10].ljust(10, "0")


def load_tree(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def node_text(nodes: dict, code: str) -> str:
    node = nodes.get(code)
    if not node:
        return ""
    parts = []
    for ancestor in node.get("path", [])[-3:]:
        item = nodes.get(ancestor)
        if item and item.get("description"):
            parts.append(item["description"])
    if not parts:
        parts.append(node.get("description", ""))
    return " | ".join(parts)[:700]


def build_pairs(data_path: Path, tree_path: Path, max_samples: int, seed: int, language: str | None = None) -> tuple[list, list]:
    tree = load_tree(tree_path)
    nodes = tree["nodes"]
    rng = random.Random(seed)
    rows = []
    with data_path.open(encoding="utf-8") as handle:
        for line in handle:
            if len(rows) >= max_samples:
                break
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if language and str(row.get("language") or "").lower() != language:
                continue
            code = digits(row.get("taric10") or row.get("cn8"))
            node = nodes.get(code)
            if not node:
                # CN8 often maps to its 10-digit leaf with zero suffix.
                prefix = code[:8]
                node = next((n for c, n in nodes.items() if c.startswith(prefix) and not n["children"]), None)
            if not node or not node.get("description"):
                continue
            positive = node_text(nodes, node["code"])
            siblings = [c for c in nodes.get(node.get("parent_code") or "", {}).get("children", []) if c != node["code"]]
            hard = nodes[rng.choice(siblings)]["description"] if siblings else ""
            other = rng.choice(list(nodes.values()))
            rows.append({
                "id": row.get("id"),
                "query": (row.get("description") or "")[:1200],
                "positive": positive,
                "hard_negative": hard,
                "random_negative": other.get("description", "")[:700],
            })
    rng.shuffle(rows)
    split = max(1, int(len(rows) * 0.9))
    return rows[:split], rows[split:]


def make_examples(rows: list):
    from sentence_transformers import InputExample

    examples = []
    for row in rows:
        examples.append(InputExample(texts=[row["query"], row["positive"]], label=1.0))
        if row["hard_negative"]:
            examples.append(InputExample(texts=[row["query"], row["hard_negative"]], label=0.0))
        if row["random_negative"]:
            examples.append(InputExample(texts=[row["query"], row["random_negative"]], label=0.0))
    return examples


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--tree", type=Path, default=TREE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-samples", type=int, default=6000)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--model", default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
    parser.add_argument("--language", default=None)
    args = parser.parse_args()
    if not args.data.is_file():
        raise SystemExit(f"No EBTI data at {args.data}")
    train_rows, eval_rows = build_pairs(args.data, args.tree, args.max_samples, args.seed, args.language)
    print(f"train rows={len(train_rows)} eval rows={len(eval_rows)}", flush=True)
    from sentence_transformers import CrossEncoder
    from torch.utils.data import DataLoader

    model = CrossEncoder(args.model, num_labels=1, max_length=256, device="cpu")
    train_loader = DataLoader(make_examples(train_rows), shuffle=True, batch_size=args.batch_size)
    args.output.mkdir(parents=True, exist_ok=True)
    model.fit(
        train_dataloader=train_loader,
        epochs=args.epochs,
        warmup_steps=max(1, len(train_loader) // 10),
        output_path=str(args.output),
        show_progress_bar=True,
    )
    model.save(str(args.output))
    # Simple held-out evaluation: positive should outrank its negative.
    pairs, labels = [], []
    for row in eval_rows:
        if row["positive"]:
            pairs.append([row["query"], row["positive"]]); labels.append(1)
        if row["hard_negative"]:
            pairs.append([row["query"], row["hard_negative"]]); labels.append(0)
    scores = model.predict(pairs, batch_size=args.batch_size, show_progress_bar=False)
    pos = [float(s) for s, y in zip(scores, labels) if y == 1]
    neg = [float(s) for s, y in zip(scores, labels) if y == 0]
    metrics = {
        "model": args.model,
        "train_rows": len(train_rows),
        "eval_rows": len(eval_rows),
        "positive_mean": round(sum(pos) / len(pos), 4) if pos else None,
        "negative_mean": round(sum(neg) / len(neg), 4) if neg else None,
        "pair_accuracy": round(sum(1 for p in pos for n in neg if p > n) / max(1, len(pos) * len(neg)), 4),
    }
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2), flush=True)
    print("saved:", args.output, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
