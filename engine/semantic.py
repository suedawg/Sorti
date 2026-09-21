"""
Local Semantic Classification Engine for Sorti.
Uses bundled offline BAAI/bge-small-en-v1.5 ONNX model via fastembed.
Zero API keys, 100% offline CPU inference (<15ms).
"""

from pathlib import Path
import sys
import os
import threading
import numpy as np
from typing import Dict, List, Any, Optional

# Enforce 100% offline execution - zero network requests or external calls
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

class LocalSemanticClassifier:
    def __init__(self, cache_dir: Optional[Path] = None, lazy: bool = True):
        if cache_dir is None:
            # Check if running inside PyInstaller bundle
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                cache_dir = Path(sys._MEIPASS) / "model_cache"
            else:
                cache_dir = Path(__file__).parent.parent / "model_cache"
        self.cache_dir = Path(cache_dir).resolve()
        self.model = None
        self.reranker = None
        self._lock = threading.Lock()
        self._init_event = threading.Event()

        if lazy:
            # Non-blocking warm-up in background thread so app boots in <0.3s
            self._warmup_thread = threading.Thread(target=self._init_model, daemon=True)
            self._warmup_thread.start()
        else:
            self._init_model()

    def _init_model(self):
        with self._lock:
            if self.model is not None:
                self._init_event.set()
                return
            try:
                from fastembed import TextEmbedding
                # local_files_only=True ensures no network access or HF API key is ever required
                self.model = TextEmbedding(
                    model_name="BAAI/bge-small-en-v1.5",
                    cache_dir=str(self.cache_dir),
                    local_files_only=True,
                    threads=2
                )
            except Exception as e:
                print(f"[SemanticClassifier] Note: offline fastembed embedding fallback: {e}")
                self.model = None

            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
                self.reranker = TextCrossEncoder(
                    model_name="Xenova/ms-marco-MiniLM-L-6-v2",
                    cache_dir=str(self.cache_dir),
                    local_files_only=True,
                    threads=2
                )
            except Exception as e:
                print(f"[SemanticClassifier] Note: offline fastembed reranker fallback: {e}")
                self.reranker = None
            finally:
                self._init_event.set()

    def rerank(self, query: str, documents: List[str]) -> List[float]:
        """
        Reranks documents against query using local cross-encoder.
        Returns list of float scores in the same order as documents.
        """
        if not query or not documents:
            return [0.0] * len(documents)
        if self.reranker is None and not self._init_event.is_set():
            self._init_event.wait(timeout=2.5)
        if not self.reranker:
            return [0.0] * len(documents)
        try:
            results = list(self.reranker.rerank(query, documents))
            return [float(s) for s in results]
        except Exception as e:
            print(f"[SemanticClassifier] Rerank error: {e}")
            return [0.0] * len(documents)

    def embed_text(self, text: str) -> Optional[np.ndarray]:
        """Embeds text into a normalized 384-dim dense vector."""
        if not text or not text.strip():
            return None

        # If model is still warming up in background, wait briefly
        if self.model is None and not self._init_event.is_set():
            self._init_event.wait(timeout=2.5)

        if not self.model:
            return None
        try:
            short_text = " ".join(text.strip().split()[:350])
            embeddings = list(self.model.embed([short_text]))
            if embeddings:
                vec = np.array(embeddings[0], dtype=np.float32)
                norm = float(np.linalg.norm(vec))
                if norm > 0:
                    return vec / norm
                return vec
        except Exception as e:
            print(f"[SemanticClassifier] Embedding error: {e}")
        return None

    def cosine_similarity(self, vec1: Optional[np.ndarray], vec2: Optional[np.ndarray]) -> float:
        """Calculates cosine similarity between two normalized vectors."""
        if vec1 is None or vec2 is None:
            return 0.0
        try:
            return float(np.dot(vec1, vec2))
        except Exception:
            return 0.0
