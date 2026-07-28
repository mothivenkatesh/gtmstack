#!/usr/bin/env python3
"""
Eval harness for Listener's classifiers.

The PRD states an accuracy target (precision 0.85, recall 0.70, precision first
because alert fatigue kills adoption faster than a missed post does). Until this
file existed that target was a sentence in a document. Now it is a number that
either passes or fails.

What this is NOT: a unit test. Unit tests assert behaviour is correct. An eval
measures how correct, on a labelled sample, and tracks whether a change made it
better or worse. Both matter, and they fail for different reasons.

    python evals/run_evals.py              # human-readable report
    python evals/run_evals.py --json       # machine-readable, for CI
    python evals/run_evals.py --gate       # exit 1 if below target (CI gate)

The report deliberately splits EASY from HARD cases. The current classifier is a
keyword heuristic, so it is expected to do well on explicit phrasing and badly on
sarcasm, negation, and implicit intent. Reporting one blended number would hide
exactly the gap that decides whether a real classifier is needed.

No em dashes.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "api"))

from _agents import _intent, _sentiment    # noqa: E402

# The PRD's targets. Precision first, on purpose.
TARGETS = {"intent_precision": 0.85, "intent_recall": 0.70, "sentiment_accuracy": 0.80}

BUYING = ("category_intent", "competitor_comparison")


def load():
    with open(os.path.join(HERE, "golden_intent.json"), encoding="utf-8") as f:
        return json.load(f)["cases"]


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return round(p, 3), round(r, 3), round(f, 3)


def evaluate(cases):
    """Score the classifiers. The headline metric is BUYING-INTENT detection,
    because that is the alert that actually reaches a human: a false positive
    there is a wasted interruption, which is the failure mode that kills trust."""
    tp = fp = fn = 0
    intent_hits = sent_hits = 0
    misses = []

    for c in cases:
        got_i, got_s = _intent(c["text"]), _sentiment(c["text"])
        want_i, want_s = c["intent"], c["sentiment"]

        if got_i == want_i:
            intent_hits += 1
        else:
            misses.append({"text": c["text"][:74], "field": "intent",
                           "want": want_i, "got": got_i, "hard": c.get("hard", False)})
        if got_s == want_s:
            sent_hits += 1
        elif got_i == want_i:
            misses.append({"text": c["text"][:74], "field": "sentiment",
                           "want": want_s, "got": got_s, "hard": c.get("hard", False)})

        want_buy, got_buy = want_i in BUYING, got_i in BUYING
        if got_buy and want_buy:
            tp += 1
        elif got_buy and not want_buy:
            fp += 1
        elif want_buy and not got_buy:
            fn += 1

    p, r, f1 = _prf(tp, fp, fn)
    n = len(cases) or 1
    return {
        "n": len(cases),
        "intent_precision": p, "intent_recall": r, "intent_f1": f1,
        "tp": tp, "fp": fp, "fn": fn,
        "intent_accuracy": round(intent_hits / n, 3),
        "sentiment_accuracy": round(sent_hits / n, 3),
        "misses": misses,
    }


def main():
    args = sys.argv[1:]
    cases = load()
    easy = [c for c in cases if not c.get("hard")]
    hard = [c for c in cases if c.get("hard")]

    overall, r_easy, r_hard = evaluate(cases), evaluate(easy), evaluate(hard)
    failures = {k: (overall[k], t) for k, t in TARGETS.items() if overall[k] < t}
    report = {"overall": overall, "easy": r_easy, "hard": r_hard,
              "targets": TARGETS, "passing": not failures, "failures": failures}

    if "--json" in args:
        print(json.dumps(report, indent=2))
    else:
        print("\nListener classifier evals")
        print("=" * 62)
        print(f"golden set: {overall['n']} cases  ({len(easy)} explicit, {len(hard)} hard)\n")
        print(f"{'metric':<26}{'overall':>9}{'explicit':>10}{'hard':>8}{'target':>9}")
        print("-" * 62)
        for k, label in (("intent_precision", "buying-intent precision"),
                         ("intent_recall", "buying-intent recall"),
                         ("intent_f1", "buying-intent F1"),
                         ("intent_accuracy", "intent accuracy"),
                         ("sentiment_accuracy", "sentiment accuracy")):
            t = TARGETS.get(k)
            mark = "" if t is None else ("  PASS" if overall[k] >= t else "  FAIL")
            print(f"{label:<26}{overall[k]:>9}{r_easy[k]:>10}{r_hard[k]:>8}"
                  f"{(t if t is not None else '-'):>9}{mark}")
        print("-" * 62)
        print(f"confusion (buying intent): tp={overall['tp']} fp={overall['fp']} "
              f"fn={overall['fn']}")

        if overall["misses"]:
            hard_misses = [m for m in overall["misses"] if m["hard"]]
            easy_misses = [m for m in overall["misses"] if not m["hard"]]
            print(f"\nmisses: {len(easy_misses)} on explicit cases, "
                  f"{len(hard_misses)} on hard cases")
            for m in easy_misses[:8]:
                print(f"   [explicit] {m['field']}: want {m['want']}, got {m['got']}"
                      f"\n              \"{m['text']}\"")
            for m in hard_misses[:6]:
                print(f"   [hard]     {m['field']}: want {m['want']}, got {m['got']}"
                      f"\n              \"{m['text']}\"")

        print("\nverdict:", "PASSING" if report["passing"] else "BELOW TARGET")
        if failures:
            for k, (got, want) in failures.items():
                print(f"   {k}: {got} < {want}")
            print("\nThe classifier is a keyword heuristic (_intent/_sentiment in\n"
                  "api/_agents.py). Hard cases need real NLU. Closing this gap is\n"
                  "the next increment, and this file is how it gets measured.")
        print()

    if "--gate" in args and not report["passing"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
