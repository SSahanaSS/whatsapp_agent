"""
faq_tools.py (FIXED)

Fixes:
✅ No global cursor/connection
✅ Fresh DB connection per query
✅ Auto retry on failure
✅ Safe closing of cursor/connection
"""

import re
import psycopg2
from datetime import datetime
import pytz
from google import genai
from google.genai import types
from config import NEON_CONNECTION_STRING, GEMINI_API_KEY

IST = pytz.timezone("Asia/Kolkata")

# ─────────────────────────────────────────────────────────────────────────────
# Gemini Client
# ─────────────────────────────────────────────────────────────────────────────
gemini_client = genai.Client(api_key=GEMINI_API_KEY)


# ─────────────────────────────────────────────────────────────────────────────
# DB CONNECTION (SAFE)
# ─────────────────────────────────────────────────────────────────────────────
def get_connection():
    return psycopg2.connect(
        NEON_CONNECTION_STRING,
        sslmode="require"
    )


def safe_db_execute(query, params=None, retries=2):
    for attempt in range(retries):
        conn = None
        cur = None
        try:
            conn = get_connection()
            cur = conn.cursor()

            cur.execute(query, params)
            rows = cur.fetchall()

            return rows

        except Exception as e:
            print(f"[DB ERROR attempt {attempt+1}] {e}")

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    return []


# ─────────────────────────────────────────────────────────────────────────────
# EMBEDDING
# ─────────────────────────────────────────────────────────────────────────────
def embed_query(text: str) -> list:
    result = gemini_client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
    )
    return result.embeddings[0].values


# ─────────────────────────────────────────────────────────────────────────────
# HYBRID SEARCH (FIXED)
# ─────────────────────────────────────────────────────────────────────────────
def hybrid_search(query: str, top_k: int = 10) -> list:
    query_embedding = embed_query(query)

    rows = safe_db_execute("""
        SELECT
            id,
            section,
            question,
            answer,
            chunk,
            1 - (embedding <=> %s::vector(3072)) AS semantic_score
        FROM faq_embeddings
        ORDER BY semantic_score DESC
        LIMIT %s
    """, (query_embedding, top_k))

    if not rows:
        return []

    stop_words = {
        "do","you","is","the","a","an","i","what","how","can","are","your",
        "my","in","on","at","to","for","of","and","or","with","it","we",
        "they","have","has","will","be","this","that","there","when",
        "where","which","who","by"
    }

    query_words = set(
        w.lower() for w in re.findall(r'\w+', query)
        if w.lower() not in stop_words and len(w) > 2
    )

    candidates = []

    for row in rows:
        chunk_id, section, question, answer, chunk, semantic_score = row

        chunk_words = set(w.lower() for w in re.findall(r'\w+', chunk or ""))

        keyword_overlap = (
            len(query_words & chunk_words) / len(query_words)
            if query_words else 0.0
        )

        candidates.append({
            "id": chunk_id,
            "section": section,
            "question": question,
            "answer": answer,
            "chunk": chunk,
            "semantic_score": round(float(semantic_score), 4),
            "keyword_score": round(keyword_overlap, 4),
        })

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# MMR
# ─────────────────────────────────────────────────────────────────────────────
def mmr_selection(candidates: list, top_k: int = 3, lambda_param: float = 0.7) -> list:
    if len(candidates) <= top_k:
        return candidates

    selected = []
    remaining = candidates.copy()

    for _ in range(top_k):
        best_score = -1
        best_candidate = None

        for candidate in remaining:
            relevance = candidate["semantic_score"]

            if not selected:
                diversity = 1.0
            else:
                candidate_words = set(re.findall(r'\w+', candidate["chunk"] or ""))
                max_sim = 0

                for sel in selected:
                    sel_words = set(re.findall(r'\w+', sel["chunk"] or ""))
                    if candidate_words or sel_words:
                        overlap = len(candidate_words & sel_words) / len(candidate_words | sel_words)
                        max_sim = max(max_sim, overlap)

                diversity = 1.0 - max_sim

            score = lambda_param * relevance + (1 - lambda_param) * diversity

            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate:
            selected.append(best_candidate)
            remaining.remove(best_candidate)

    return selected


# ─────────────────────────────────────────────────────────────────────────────
# SCORING
# ─────────────────────────────────────────────────────────────────────────────
def compute_answer_quality(answer: str) -> float:
    if not answer:
        return 0.0

    word_count = len(answer.split())

    if word_count < 5:
        length_score = 0.2
    elif word_count < 15:
        length_score = 0.5
    elif word_count <= 60:
        length_score = 1.0
    elif word_count <= 100:
        length_score = 0.8
    else:
        length_score = 0.6

    specificity_score = 0.5
    if re.search(r'\d', answer): specificity_score += 0.1
    if re.search(r'\d+\s*(am|pm)', answer.lower()): specificity_score += 0.2
    if "deliver" in answer.lower(): specificity_score += 0.1

    return round((length_score * 0.6 + specificity_score * 0.4), 4)


def compute_confidence(semantic_score, keyword_score, answer_quality):
    return round(
        0.5 * semantic_score +
        0.3 * keyword_score +
        0.2 * answer_quality,
        4
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TOOL
# ─────────────────────────────────────────────────────────────────────────────
def search_faq(query: str) -> dict:
    print(f"      [FAQ Tools] Hybrid search for: '{query}'")

    candidates = hybrid_search(query)

    if not candidates:
        return {
            "found": False,
            "results": [],
            "top_confidence": 0.0
        }

    selected = mmr_selection(candidates)

    scored = []

    for c in selected:
        aq = compute_answer_quality(c["answer"])
        conf = compute_confidence(
            c["semantic_score"],
            c["keyword_score"],
            aq
        )

        scored.append({
            **c,
            "answer_quality": aq,
            "confidence": conf
        })

    scored.sort(key=lambda x: x["confidence"], reverse=True)

    return {
        "found": True,
        "results": scored,
        "top_confidence": scored[0]["confidence"],
        "top_answer": scored[0]["answer"]
    }
# ─────────────────────────────────────────────────────────────────────────────
# MENU SEARCH (FIXED - NO GLOBAL CURSOR)
# ─────────────────────────────────────────────────────────────────────────────
def search_menu_info(query: str) -> dict:
    print(f"      [FAQ Tools] Menu search for: '{query}'")
    now_ist = datetime.now(IST).time().replace(microsecond=0)

    rows = safe_db_execute("""
        SELECT item_id, item_name, price, availability, available_from, available_until
        FROM menu
        WHERE LOWER(item_name) LIKE LOWER(%s)
        AND availability = TRUE
        ORDER BY available_from, item_id
    """, (f"%{query}%",))

    if not rows:
        return {
            "found": False,
            "items": [],
            "message": f"No menu item found matching '{query}'"
        }

    return {
        "found": True,
        "items": [
            {
                "item_id": r[0],
                "item_name": r[1],
                "price": float(r[2]),
                "available": r[3],
                "available_from": str(r[4]),
                "available_until": str(r[5]),
                "currently_available": bool(r[4] <= now_ist <= r[5]),
            }
            for r in rows
        ]
    }
