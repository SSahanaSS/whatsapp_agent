"""
evaluate_ragas.py
-----------------
Offline RAGAS evaluation for Amma's Kitchen FAQ Agent.

Reads:   ragas_log.jsonl  (written by faq_agent._log_to_ragas)
Outputs: ragas_results.csv  +  summary printed to stdout

Metrics (NO LLM calls — zero rate limiting)
--------------------------------------------
  • NonLLMStringSimilarity — Levenshtein-based similarity (catches near-identical answers)
  • SemanticSimilarity     — embedding-based meaning match (handles paraphrasing correctly)

Ground truths are automatically injected from Amma's Kitchen FAQ for known questions.
Unknown questions fall back to any ground_truth already in the log.

Embeddings model: sentence-transformers/all-MiniLM-L6-v2  (local, no API key needed)
No Groq / OpenAI calls made. Runs in ~30 seconds for any dataset size.

Usage
-----
  python evaluate_ragas.py                        # uses ragas_log.jsonl
  python evaluate_ragas.py --log my_other.jsonl  # custom log file
  python evaluate_ragas.py --limit 20            # evaluate latest N records only

Install
-------
  pip install ragas langchain-community sentence-transformers==2.7.0 datasets tf-keras -q
"""

import os
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"  # suppress TensorFlow noise

import argparse
import csv
import json
import sys
import time
from pathlib import Path

# ── Dependency check ──────────────────────────────────────────────────────────
def _check_deps():
    missing = []
    for pkg, install_name in [
        ("ragas",                 "ragas"),
        ("langchain_community",   "langchain-community"),
        ("sentence_transformers", "sentence-transformers==2.7.0"),
        ("datasets",              "datasets"),
    ]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(install_name)
    if missing:
        print(
            "[ERROR] Missing packages. Install with:\n"
            f"  pip install {' '.join(missing)}"
        )
        sys.exit(1)

_check_deps()

# ── Imports ───────────────────────────────────────────────────────────────────
from datasets import Dataset
from langchain_community.embeddings import HuggingFaceEmbeddings
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.metrics.collections import SemanticSimilarity, NonLLMStringSimilarity

# ── Config ────────────────────────────────────────────────────────────────────
EMBEDDINGS_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_LOG      = "ragas_log.jsonl"
OUTPUT_CSV       = "ragas_results.csv"

METRICS            = [NonLLMStringSimilarity(), SemanticSimilarity()]
NEEDS_GROUND_TRUTH = {"non_llm_string_similarity", "semantic_similarity"}
NEEDS_EMBEDDINGS   = {"semantic_similarity"}


# ── Ground truth lookup from Amma's Kitchen FAQ ───────────────────────────────
# Keys are lowercase normalized question fragments for fuzzy matching.
# Values are the exact correct answers from the FAQ PDF.

FAQ_GROUND_TRUTHS: list[tuple[str, str]] = [
    # Delivery
    ("which areas do you deliver",
     "We currently deliver to Adyar, Velachery, T.Nagar, Mylapore, and Nungambakkam. We do not deliver outside these areas at the moment."),
    ("delivery timings",
     "We deliver lunch orders from 12:00 PM to 2:00 PM and dinner orders from 7:00 PM to 9:00 PM, Monday to Saturday."),
    ("deliver on sunday",
     "No, we are closed on Sundays. Our kitchen operates Monday to Saturday only."),
    ("delivery charge",
     "Delivery is free for orders above Rs.200. A delivery charge of Rs.30 applies for orders below Rs.200."),
    ("minimum order",
     "The minimum order value is Rs.100."),
    ("how long does delivery",
     "Delivery typically takes 30 to 45 minutes from the time your order is confirmed."),
    # Ordering
    ("how do i place an order",
     "Simply send us a WhatsApp message with the items you want. Our chatbot will guide you through the ordering process and send you a payment link to complete your order."),
    ("modify my order",
     "You can modify your order within 5 minutes of placing it. After that, the order goes to the kitchen and cannot be changed."),
    ("schedule an order",
     "Yes! You can place an order up to one day in advance by mentioning your preferred delivery time in the chat."),
    ("bulk",
     "Yes, we accept bulk and catering orders. Please contact us at least 2 days in advance for bulk orders above 20 items."),
    ("catering",
     "Yes, we accept bulk and catering orders. Please contact us at least 2 days in advance for bulk orders above 20 items."),
    # Payment
    ("payment methods",
     "We accept all UPI payments (GPay, PhonePe, Paytm) and debit or credit cards through our secure Razorpay payment link."),
    ("cash on delivery",
     "No, we only accept online payments through our Razorpay payment link. Cash on delivery is not available."),
    ("when do i pay",
     "Payment is collected after you confirm your order. We will send you a secure payment link via WhatsApp. Your order is confirmed only after payment is completed."),
    # Food
    ("freshly made",
     "Yes, all our food is freshly prepared daily in our home kitchen. We use no preservatives or artificial additives."),
    ("sambar",
     "Our sambar is made with toor dal, fresh tomatoes, tamarind, pearl onions, and a blend of home-ground spices. It is completely vegetarian."),
    ("vegan",
     "Most of our dishes are vegetarian. Idli, dosa, pongal, and upma are all vegan-friendly as we use no dairy in these items. However, our chutney may contain coconut milk."),
    ("allergen",
     "Our kitchen handles gluten, dairy, and nuts. Please inform us of any allergies when placing your order so we can take extra precautions."),
    ("chutney",
     "We serve coconut chutney made with fresh coconut, roasted chana dal, green chillies, ginger, and a tempering of mustard seeds and curry leaves."),
    # Cancellation & Refunds
    ("cancel my order",
     "You can cancel your order within 10 minutes of placing it. After 10 minutes, the food preparation begins and cancellations are not possible."),
    ("refund",
     "We do not offer cash refunds. However, if your order is wrong, missing items, or below quality, we will replace it or provide a credit for your next order."),
    ("order is late",
     "If your order is delayed beyond 60 minutes, please contact us on WhatsApp and we will provide a discount on your next order."),
    # Support
    ("how do i contact",
     "You can reach us directly on WhatsApp at any time during our working hours, Monday to Saturday, 10:00 AM to 10:00 PM."),
    ("chatbot does not understand",
     "If the chatbot is unable to help, type 'help' or 'support' and a human will respond to you shortly during working hours."),
]


def lookup_ground_truth(question: str) -> str:
    """
    Match a question to its FAQ ground truth using simple keyword substring matching.
    Returns empty string if no match found (score will be skipped for that record).
    """
    q = question.lower()
    best_match = ""
    for keyword, answer in FAQ_GROUND_TRUTHS:
        if keyword in q:
            best_match = answer
            break  # first match wins; order in FAQ_GROUND_TRUTHS is priority order
    return best_match


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_log(path: str, limit: int | None = None) -> list[dict]:
    records = []
    log_path = Path(path)
    if not log_path.exists():
        print(f"[ERROR] Log file not found: {path}")
        sys.exit(1)

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] Skipping bad line: {e}")

    if not records:
        print("[ERROR] No valid records found in log file.")
        sys.exit(1)

    if limit:
        records = records[-limit:]

    print(f"[INFO] Loaded {len(records)} records from {path}")
    return records


def build_dataset(records: list[dict]) -> tuple[Dataset, list[str], int]:
    questions, answers, contexts, ground_truths = [], [], [], []
    warnings   = []
    skipped    = 0
    gt_injected = 0
    gt_missing  = 0

    for i, r in enumerate(records):
        q  = (r.get("question") or "").strip()
        a  = (r.get("answer")   or "").strip()
        c  = r.get("contexts") or []
        gt = (r.get("ground_truth") or "").strip()

        if not q or not a:
            warnings.append(f"Record {i}: missing question or answer — skipped")
            skipped += 1
            continue

        if not c:
            c = ["(no context retrieved)"]
            warnings.append(f"Record {i}: no contexts — using placeholder")

        # Inject ground truth from FAQ if not already present in log
        if not gt:
            gt = lookup_ground_truth(q)
            if gt:
                gt_injected += 1
            else:
                gt_missing += 1
                warnings.append(
                    f"Record {i}: '{q[:50]}' — no ground truth found, "
                    "scores will be NaN for this record"
                )

        questions.append(q)
        answers.append(a)
        contexts.append(c)
        ground_truths.append(gt)

    if skipped:
        print(f"[WARN] Skipped {skipped} records (missing question/answer)")
    if gt_injected:
        print(f"[INFO] Ground truth auto-injected for {gt_injected} records from FAQ")
    if gt_missing:
        print(f"[WARN] No ground truth found for {gt_missing} records — those rows will score NaN")

    dataset = Dataset.from_dict({
        "question":     questions,
        "answer":       answers,
        "contexts":     contexts,
        "ground_truth": ground_truths,
    })
    return dataset, warnings, skipped


def save_csv(records: list[dict], scores: dict, path: str) -> None:
    metric_names = list(scores.keys())

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "question", "answer", "confidence", "search_count",
                "ground_truth", "timestamp", *metric_names
            ]
        )
        writer.writeheader()

        valid_idx = 0
        for r in records:
            q = (r.get("question") or "").strip()
            a = (r.get("answer")   or "").strip()
            if not q or not a:
                continue

            # Resolve ground truth same way as build_dataset
            gt = (r.get("ground_truth") or "").strip() or lookup_ground_truth(q)

            row = {
                "question":     q,
                "answer":       a,
                "confidence":   r.get("confidence", ""),
                "search_count": r.get("search_count", ""),
                "ground_truth": gt,
                "timestamp":    r.get("timestamp", ""),
            }
            for m in metric_names:
                vals = scores[m]
                row[m] = round(vals[valid_idx], 4) if valid_idx < len(vals) else ""
            writer.writerow(row)
            valid_idx += 1

    print(f"[INFO] Results saved → {path}")


def print_summary(scores: dict, n: int) -> None:
    print("\n" + "═" * 55)
    print(f"  RAGAS Evaluation Summary  ({n} records, no LLM calls)")
    print("═" * 55)
    for metric, vals in scores.items():
        valid_vals = [v for v in vals if v is not None and str(v) != "nan"]
        avg = sum(valid_vals) / len(valid_vals) if valid_vals else 0.0
        scored = len(valid_vals)
        bar_len = int(avg * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"  {metric:<28} {avg:.4f}  |{bar}|  ({scored}/{n} records scored)")
    print("═" * 55 + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RAGAS evaluation for Amma's Kitchen FAQ Agent")
    parser.add_argument("--log",   default=DEFAULT_LOG, help="Path to ragas_log.jsonl")
    parser.add_argument("--limit", type=int, default=None, help="Evaluate latest N records")
    parser.add_argument("--out",   default=OUTPUT_CSV,  help="Output CSV path")
    args = parser.parse_args()

    # ── Load data ─────────────────────────────────────────────────────────────
    records = load_log(args.log, limit=args.limit)

    # ── Build dataset (auto-injects ground truths) ────────────────────────────
    dataset, warnings, _ = build_dataset(records)
    for w in warnings:
        print(f"[WARN] {w}")

    if len(dataset) == 0:
        print("[ERROR] No valid rows to evaluate.")
        sys.exit(1)

    # ── Set up local embeddings (the only model needed) ───────────────────────
    print(f"\n[INFO] Loading embeddings: {EMBEDDINGS_MODEL}  (local, no API key)")
    hf_embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name=EMBEDDINGS_MODEL)
    )

    # ── Inject embeddings into metrics that need it ───────────────────────────
    for m in METRICS:
        if hasattr(m, "embeddings") and m.name in NEEDS_EMBEDDINGS:
            m.embeddings = hf_embeddings

    # ── Run RAGAS (no LLM — very fast) ───────────────────────────────────────
    n = len(dataset)
    print(f"[INFO] Running RAGAS on {n} records (no LLM calls — expect <60s)...\n")
    t0 = time.time()

    try:
        result = evaluate(
            dataset=dataset,
            metrics=METRICS,
            raise_exceptions=False,
        )
    except Exception as e:
        print(f"[ERROR] RAGAS evaluation failed: {e}")
        sys.exit(1)

    elapsed = time.time() - t0
    print(f"\n[INFO] Evaluation done in {elapsed:.1f}s")

    # ── Extract scores ────────────────────────────────────────────────────────
    result_df = result.to_pandas()
    scores    = {}
    for m in METRICS:
        name = m.name
        if name in result_df.columns:
            scores[name] = result_df[name].tolist()
        else:
            print(f"[WARN] Metric '{name}' not in results — skipped")

    # ── Print + save ──────────────────────────────────────────────────────────
    print_summary(scores, n)
    save_csv(records, scores, args.out)


if __name__ == "__main__":
    main()