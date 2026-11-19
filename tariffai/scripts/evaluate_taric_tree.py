#!/usr/bin/env python3
"""Automated TARIC-tree retrieval benchmark.

Generates queries from official tree descriptions (not from manual test
products), samples leaves per chapter, and reports:
  * heading_hit@5: expected heading among the tree hints
  * code_hit@20: expected TARIC10/CN8 among retrieved candidates
  * cn8_hit@20: expected CN8 prefix among retrieved candidates
Results are aggregated by chapter and subheading.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.eu_retriever import retrieve_eu_candidates, retrieve_heading_pool  # noqa: E402
from app.taric_tree import load_tree, node_view  # noqa: E402
from app.tree_index import tree_hints  # noqa: E402
from app.tree_questions import question_from_candidates  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-chapter", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "taric_tree_benchmark")
    args = parser.parse_args()

    tree = load_tree()
    leaves_by_chapter: dict[str, list[str]] = defaultdict(list)
    for code, node in tree["nodes"].items():
        if not node["children"]:
            leaves_by_chapter[code[:2]].append(code)
    rng = random.Random(args.seed)
    cases = []
    for chapter in sorted(leaves_by_chapter):
        leaves = sorted(leaves_by_chapter[chapter])
        rng.shuffle(leaves)
        for code in leaves[: args.per_chapter]:
            view = node_view(code)
            if not view:
                continue
            descriptions = [item["description"] for item in view["path_nodes"] if item.get("description")]
            query = " | ".join(descriptions)
            cases.append({"code": code, "chapter": chapter, "subheading": code[:6], "query": query})

    rows = []
    for index, case in enumerate(cases, 1):
        expected = case["code"]
        hint_list = tree_hints(case["query"], top_k=5)
        hints = {item["heading"] for item in hint_list}
        candidates = retrieve_eu_candidates(case["query"], top_k=args.top_k, family_hints=hint_list)
        codes = [candidate.taric10 or candidate.cn8 for candidate in candidates]
        exact = any(code and (code == expected or code.startswith(expected) or expected.startswith(code)) for code in codes)
        cn8 = any(code and code[:8] == expected[:8] for code in codes)
        heading_hit = expected[:4] in hints

        # Family pool: all codes under the hinted headings, independent of
        # vector rank. Then simulate the tree questions using the known branch.
        pool = retrieve_heading_pool([item["heading"] for item in hint_list])
        pool_codes = [candidate.taric10 or candidate.cn8 for candidate in pool]
        pool_coverage = any(code and (code == expected or code.startswith(expected) or expected.startswith(code)) for code in pool_codes)
        expected_path = node_view(expected)["path"] if node_view(expected) else []
        current = pool
        questions = 0
        tree_success = False
        while questions < 3:
            question = question_from_candidates(current)
            if not question or not expected_path:
                break
            parent = question.get("parent_code")
            if parent not in expected_path:
                break
            index = expected_path.index(parent) + 1
            if index >= len(expected_path):
                break
            child = expected_path[index]
            if child not in question.get("option_codes", []):
                break
            current = [
                candidate for candidate in current
                if child in (node_view(candidate.taric10 or candidate.cn8) or {}).get("path", [])
            ]
            questions += 1
        tree_success = any(
            (candidate.taric10 or candidate.cn8) == expected or
            (candidate.taric10 or candidate.cn8).startswith(expected) or
            expected.startswith(candidate.taric10 or candidate.cn8)
            for candidate in current
        )
        rows.append({
            **case,
            "hints": ";".join(sorted(hints)),
            "candidate_count": len(candidates),
            "heading_hit": heading_hit,
            "code_hit": exact,
            "cn8_hit": cn8,
            "pool_count": len(pool),
            "pool_coverage": pool_coverage,
            "tree_questions": questions,
            "tree_success": tree_success,
            "candidates": ";".join(codes),
        })
        print(f"{index}/{len(cases)} {expected} heading={heading_hit} code={exact} cn8={cn8}", flush=True)

    def rate(items: list[dict], key: str) -> float:
        return round(sum(1 for item in items if item[key]) / len(items), 4) if items else 0.0

    by_chapter = {}
    for group in sorted({row["chapter"] for row in rows}):
        subset = [row for row in rows if row["chapter"] == group]
        by_chapter[group] = {
            "cases": len(subset),
            "heading_hit@5": rate(subset, "heading_hit"),
            "code_hit@20": rate(subset, "code_hit"),
            "cn8_hit@20": rate(subset, "cn8_hit"),
            "pool_coverage": rate(subset, "pool_coverage"),
            "pool_coverage_if_heading_hit": rate([row for row in subset if row["heading_hit"]], "pool_coverage") if any(row["heading_hit"] for row in subset) else 0.0,
            "tree_success": rate(subset, "tree_success"),
            "avg_questions": round(sum(row["tree_questions"] for row in subset) / len(subset), 2) if subset else 0,
        }
    by_subheading = {}
    for group in sorted({row["subheading"] for row in rows}):
        subset = [row for row in rows if row["subheading"] == group]
        by_subheading[group] = {
            "cases": len(subset),
            "heading_hit@5": rate(subset, "heading_hit"),
            "code_hit@20": rate(subset, "code_hit"),
            "cn8_hit@20": rate(subset, "cn8_hit"),
        }

    summary = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "sampling": f"{args.per_chapter} leaf(s) per chapter",
        "cases": len(rows),
        "overall": {
            "heading_hit@5": rate(rows, "heading_hit"),
            "code_hit@20": rate(rows, "code_hit"),
            "cn8_hit@20": rate(rows, "cn8_hit"),
            "pool_coverage": rate(rows, "pool_coverage"),
            "pool_coverage_if_heading_hit": rate([row for row in rows if row["heading_hit"]], "pool_coverage") if any(row["heading_hit"] for row in rows) else 0.0,
            "tree_success": rate(rows, "tree_success"),
            "avg_questions": round(sum(row["tree_questions"] for row in rows) / len(rows), 2) if rows else 0,
        },
        "by_chapter": by_chapter,
        "by_subheading": by_subheading,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with args.output.with_suffix(".csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["code"])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"cases": len(rows), "overall": summary["overall"]}, ensure_ascii=False, indent=2))
    print("report:", args.output.with_suffix(".json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
