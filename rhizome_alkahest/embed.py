"""Embedding — sentence-transformers for edge text."""

import os
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

from typing import Optional

_model = None

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


def get_model():
    """Lazy-load the sentence transformer model."""
    global _model
    if _model is None:
        import os, logging
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        os.environ["TRANSFORMERS_VERBOSITY"] = "error"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
        logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
        import transformers
        transformers.logging.set_verbosity_error()
        import sys
        _fd = os.dup(2)
        _devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(_devnull, 2)  # suppress noisy C-level stderr during load
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(EMBEDDING_MODEL)
        finally:
            os.dup2(_fd, 2)
            os.close(_fd)
            os.close(_devnull)
    return _model


def edge_text(subject: str, predicate: str, object: str, notes: str = "") -> str:
    """Format an edge triple as embeddable text."""
    text = f"{subject} {predicate} {object}"
    if notes:
        text += f" — {notes}"
    return text


def embed(text: str) -> list[float]:
    """Embed a single text string."""
    model = get_model()
    return model.encode(text).tolist()


def embed_batch(texts: list[str], batch_size: int = 256) -> list[list[float]]:
    """Embed a batch of text strings."""
    model = get_model()
    return [e.tolist() for e in model.encode(texts, batch_size=batch_size, show_progress_bar=False)]


def embed_edge(subject: str, predicate: str, object: str, notes: str = "") -> list[float]:
    """Embed an edge triple."""
    return embed(edge_text(subject, predicate, object, notes))
