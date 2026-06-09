"""Grounded generation + interface for The Unofficial Guide (Milestone 5).

This implements the final stages of the planning.md pipeline:

    Retrieval (top-k = 4, cosine) -> Generation (Groq LLM) -> source-backed response

Two grounding guarantees are built in, by design:

1. Grounding is *enforced*, not merely requested.
   - The system prompt forbids outside knowledge and mandates a fixed
     refusal phrase when the context does not contain the answer.
   - Structurally, if no retrieved chunk clears RELEVANCE_THRESHOLD, the
     LLM is never called and the refusal is returned directly. The model
     cannot answer from its own parametric memory when retrieval is empty.

2. Source attribution is *programmatic*, not left to the LLM.
   - The "Sources" list is assembled in code from the retrieved chunks'
     ChromaDB metadata (source name, description, URL) and appended to the
     answer. It appears regardless of whether the model cites anything,
     so attribution can never silently go missing.
"""

from __future__ import annotations

import os
from typing import Sequence

from dotenv import load_dotenv
from groq import Groq
from sentence_transformers import SentenceTransformer

from retrieval import (
    DEFAULT_COLLECTION,
    DEFAULT_PERSIST_DIR,
    DEFAULT_TOP_K,
    EMBEDDING_MODEL,
    RetrievedChunk,
    retrieve,
)


GROQ_MODEL = "llama-3.3-70b-versatile"
# Cosine similarity floor. Chunks below this are treated as irrelevant; if
# none clear it, the question is answered with the refusal instead of the LLM.
RELEVANCE_THRESHOLD = 0.20
REFUSAL = "I don't have enough information in my sources to answer that."

SYSTEM_PROMPT = """You are The Unofficial Guide, a question-answering assistant for \
Computer Science courses at the New Jersey Institute of Technology (NJIT).

You answer ONLY using the numbered sources provided in the user message. Follow \
these rules exactly:

1. Use ONLY the information in the provided sources. Do NOT use any prior \
knowledge, outside facts, or assumptions. If a detail is not in the sources, you \
do not know it.
2. You MUST cite your sources inline. Each source below begins with a citation \
label in square brackets, e.g. "[Reddit, https://www.reddit.com/...]". Whenever \
you use information from a source, copy that exact label into your answer right \
after the claim, e.g. "CS 350 is considered hard [College Class Reviews, \
https://collegeclassreviews.com/...]". Use the label verbatim, including the \
URL. An answer with no citations is invalid.
3. If the provided sources do NOT contain enough information to answer the \
question, respond with EXACTLY this sentence and nothing else: \
"{refusal}"
4. Do not speculate, do not hedge with outside knowledge, and never invent \
course numbers, professor names, or prerequisites that are not in the sources.
5. Keep the answer concise and directly responsive to the question.""".format(
    refusal=REFUSAL
)


# Load the embedding model once and reuse it across queries.
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def get_groq_client() -> Groq:
    load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or api_key == "your_key_here":
        raise RuntimeError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return Groq(api_key=api_key)


def number_sources(results: Sequence[RetrievedChunk]) -> tuple[dict[int, int], list[dict]]:
    """Assign a stable [Source N] number per unique document, in first-seen order.

    Returns (mapping, ordered) where `mapping` is source_index -> citation
    number and `ordered` is the list of document metadata in number order.
    The model's inline [Source N] citations and the appended Sources list are
    both built from this single numbering, so they always refer to the same
    document.
    """
    mapping: dict[int, int] = {}
    ordered: list[dict] = []
    for hit in results:
        source_index = hit.metadata.get("source_index")
        if source_index not in mapping:
            mapping[source_index] = len(ordered) + 1
            ordered.append(hit.metadata)
    return mapping, ordered


def citation_label(meta: dict) -> str:
    """The exact bracketed label the model must copy when citing this source,
    e.g. "[Reddit, https://www.reddit.com/...]". The URL makes it unambiguous
    even when several sources share the same name (e.g. multiple Reddit threads).
    """
    name = meta.get("source_name", "Unknown")
    url = meta.get("source_url", "")
    return f"[{name}, {url}]"


def format_context(results: Sequence[RetrievedChunk]) -> str:
    """Render retrieved chunks for the prompt.

    Each chunk begins with its citation label in square brackets; the model is
    instructed to copy that exact label inline whenever it uses the chunk.
    """
    blocks: list[str] = []
    for hit in results:
        meta = hit.metadata
        header = f"{citation_label(meta)} — {meta.get('source_description', '')}".strip()
        blocks.append(f"{header}\n{hit.text}")
    return "\n\n".join(blocks)


def format_sources(results: Sequence[RetrievedChunk]) -> str:
    """Build the source list in code, deduplicated by document.

    This is the programmatic attribution guarantee: it is derived from chunk
    metadata, not from anything the LLM emits, so it is always present and
    always accurate. The numbering matches the inline [Source N] citations.
    """
    _, ordered = number_sources(results)
    lines: list[str] = []
    for rank, meta in enumerate(ordered, start=1):
        name = meta.get("source_name", "Unknown")
        description = meta.get("source_description", "")
        url = meta.get("source_url", "")
        lines.append(f"{rank}. **{name}** — {description}\n   {url}")
    return "\n".join(lines)


def build_messages(query: str, context: str) -> list[dict]:
    user_content = (
        f"Sources:\n\n{context}\n\n"
        f"Question: {query}\n\n"
        "Answer the question using only the sources above, citing source numbers inline."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def generate_answer(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    persist_dir=DEFAULT_PERSIST_DIR,
    collection_name: str = DEFAULT_COLLECTION,
    client: Groq | None = None,
) -> tuple[str, list[RetrievedChunk]]:
    """Retrieve, ground, and generate. Returns (answer_text, used_chunks).

    `used_chunks` is what the source list is built from, so the caller can
    render attribution that exactly matches what the model was shown.
    """
    if not query.strip():
        return "Please enter a question.", []

    results = retrieve(
        query=query,
        top_k=top_k,
        persist_dir=persist_dir,
        collection_name=collection_name,
        model=get_model(),
    )

    # Structural grounding gate: drop irrelevant chunks, and if nothing
    # relevant remains, refuse WITHOUT calling the LLM.
    relevant = [hit for hit in results if hit.similarity >= RELEVANCE_THRESHOLD]
    if not relevant:
        return REFUSAL, []

    if client is None:
        client = get_groq_client()

    context = format_context(relevant)
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=build_messages(query, context),
        temperature=0.0,  # deterministic, faithful answers
        max_tokens=600,
    )
    answer = completion.choices[0].message.content.strip()
    return answer, relevant


def format_response(answer: str, used_chunks: Sequence[RetrievedChunk]) -> str:
    """Combine the LLM answer with the code-generated source list."""
    if not used_chunks or answer.strip() == REFUSAL:
        return answer
    return f"{answer}\n\n---\n**Sources:**\n{format_sources(used_chunks)}"


def answer_question(query: str) -> str:
    """End-to-end entry point used by both the CLI and the Gradio UI."""
    answer, used_chunks = generate_answer(query)
    return format_response(answer, used_chunks)


# --------------------------------------------------------------------------- #
# Gradio interface skeleton
# --------------------------------------------------------------------------- #
def build_interface():
    import gradio as gr

    with gr.Blocks(title="The Unofficial Guide — NJIT CS") as demo:
        gr.Markdown(
            "# The Unofficial Guide\n"
            "Ask about NJIT Computer Science courses, professors, difficulty, "
            "and prerequisites. Answers come only from collected student reviews "
            "and catalog pages, with sources listed."
        )
        question = gr.Textbox(
            label="Your question",
            placeholder="e.g. What is an easy CS elective to take at NJIT?",
            lines=2,
        )
        ask = gr.Button("Ask", variant="primary")
        answer = gr.Markdown(label="Answer")

        ask.click(fn=answer_question, inputs=question, outputs=answer)
        question.submit(fn=answer_question, inputs=question, outputs=answer)

        gr.Examples(
            examples=[
                "Which CS class at NJIT is most commonly rated among the hardest?",
                "What are the prerequisites of CS 288?",
                "What is an easy CS elective to take at NJIT?",
            ],
            inputs=question,
        )

    return demo


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Grounded Q&A over NJIT CS sources.")
    parser.add_argument("--query", type=str, default=None, help="Answer one question and exit.")
    parser.add_argument("--ui", action="store_true", help="Launch the Gradio web interface.")
    parser.add_argument("--share", action="store_true", help="Create a public Gradio link.")
    args = parser.parse_args()

    if args.query is not None:
        print(answer_question(args.query))
        return 0

    if args.ui:
        build_interface().launch(share=args.share)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
