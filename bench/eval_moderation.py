"""Score active encyclopedia hazard filtering against hand-labeled flagged edits.

Run: uv run python -m bench.eval_moderation data/eval-moderation.jsonl
"""

from __future__ import annotations

import json
import sys

from wikipulse.core.hazards import filter_categories


def score(rows: list[dict]) -> dict:
    labeled = [r for r in rows if r.get("label") in ("malicious", "benign")]
    base_flagged = len(labeled)
    base_mal = sum(r["label"] == "malicious" for r in labeled)

    filtered = [r for r in labeled if filter_categories(r.get("categories", []))]
    filt_mal = sum(r["label"] == "malicious" for r in filtered)
    mal_dropped = base_mal - filt_mal

    def prec(mal: int, flagged: int) -> float:
        return round(mal / flagged, 4) if flagged else 0.0

    return {
        "baseline": {"flagged": base_flagged, "precision": prec(base_mal, base_flagged)},
        "filtered": {
            "flagged": len(filtered),
            "precision": prec(filt_mal, len(filtered)),
            "malicious_dropped": mal_dropped,
        },
    }


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "data/eval-moderation.jsonl"
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    result = score(rows)
    b, fl = result["baseline"], result["filtered"]
    print(f"labeled flagged edits: {b['flagged']}")
    print(f"  baseline precision: {b['precision']:.3f} ({b['flagged']} flagged)")
    print(f"  +filter  precision: {fl['precision']:.3f} ({fl['flagged']} flagged)")
    print(f"  filter-induced false negatives (malicious dropped): {fl['malicious_dropped']}")


if __name__ == "__main__":
    main()
