"""
setup_faq.py
------------
Run this ONCE to set up FAQ embeddings in Neon pgvector.
Embeds question + answer + keywords together for better retrieval.
"""

import pdfplumber
import psycopg2
import os
from google import genai
from google.genai import types

from config import NEON_CONNECTION_STRING, GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)
FAQ_PDF_PATH = r"D:\final-whatsapp\faq.pdf"
conn = psycopg2.connect(NEON_CONNECTION_STRING, sslmode="require")
conn.autocommit = True
cur = conn.cursor()

SECTION_KEYWORDS = {
    "Delivery":     "deliver delivery area location zone radius ship",
    "Ordering":     "order place buy purchase schedule advance bulk catering",
    "Payment":      "pay payment upi gpay phonepe paytm card cash cod online",
    "Food":         "food menu ingredients vegan vegetarian allergen fresh homemade",
    "Cancellation": "cancel refund return money back late delay compensation",
    "Contact":      "contact support help human agent reach",
    "Timings":      "timing time open close hours weekday weekend saturday sunday monday",
}


def extract_text_from_pdf(pdf_path: str) -> str:
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
    print(f"  Extracted {len(full_text)} characters from PDF")
    return full_text


def split_into_chunks(text: str) -> list:
    chunks = []
    current_section = ""
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if (line and not line.startswith("Q:")
                and not line.startswith("A:")
                and len(line) < 50):
            current_section = line
            i += 1
            continue

        if line.startswith("Q:"):
            question = line[2:].strip()
            answer_lines = []

            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if next_line.startswith("A:"):
                    answer_lines.append(next_line[2:].strip())
                    i += 1
                    while i < len(lines):
                        cont = lines[i].strip()
                        if cont.startswith("Q:") or cont.startswith("A:"):
                            break
                        if cont:
                            answer_lines.append(cont)
                        i += 1
                    break
                else:
                    i += 1

            if question and answer_lines:
                answer   = " ".join(answer_lines)
                keywords = SECTION_KEYWORDS.get(current_section, "")
                chunk    = f"{current_section}: {question} {answer} {keywords}".strip()
                chunks.append({
                    "section":  current_section,
                    "question": question,
                    "answer":   answer,
                    "chunk":    chunk,
                })
        else:
            i += 1

    print(f"  Split into {len(chunks)} Q&A chunks")
    return chunks


def embed_text(text: str) -> list:
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
    )
    return result.embeddings[0].values


def setup_db():
    cur.execute("DROP TABLE IF EXISTS faq_embeddings")
    cur.execute("""
        CREATE TABLE faq_embeddings (
            id SERIAL PRIMARY KEY,
            section TEXT,
            question TEXT,
            answer TEXT,
            chunk TEXT,
            embedding VECTOR(3072)
        )
    """)
    print("  Neon table ready (cleared old data)")


def store_chunks(chunks: list):
    for i, chunk in enumerate(chunks):
        print(f"  Embedding {i+1}/{len(chunks)}: {chunk['question'][:60]}...")
        embedding = embed_text(chunk["chunk"])
        cur.execute("""
            INSERT INTO faq_embeddings (section, question, answer, chunk, embedding)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            chunk["section"],
            chunk["question"],
            chunk["answer"],
            chunk["chunk"],
            embedding,
        ))
    print(f"  Stored {len(chunks)} chunks in Neon pgvector")


def main():
    print("\n=== FAQ RAG Setup (Neon) ===\n")

    print("Step 1: Setting up Neon table...")
    setup_db()

    print("\nStep 2: Extracting text from PDF...")
    text = extract_text_from_pdf(FAQ_PDF_PATH)

    print("\nStep 3: Splitting into Q&A chunks...")
    chunks = split_into_chunks(text)

    print(f"\nTotal chunks: {len(chunks)}")

    print("\n--- Preview ---")
    for i, c in enumerate(chunks[:3]):
        print(f"Chunk {i+1}: {c['chunk'][:120]}...")

    print("\nStep 4: Embedding and storing...")
    store_chunks(chunks)

    print("\n=== Setup Complete! ===")
    print(f"Total chunks stored: {len(chunks)}")


if __name__ == "__main__":
    main()