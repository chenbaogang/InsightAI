import re

MODEL_BGE_M3 = "BAAI/bge-m3"


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = re.findall(r"[a-z0-9_]+", text)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    tokens += cjk
    tokens += [a + b for a, b in zip(cjk, cjk[1:])]
    return tokens


class BGEEmbedder:

    def __init__(self, model_name: str | None = None) -> None:
        import torch
        from app.config import get_settings
        from sentence_transformers import SentenceTransformer

        s = get_settings()
        name = model_name or s.embedding_model_dir or MODEL_BGE_M3
        self._model = SentenceTransformer(
            _model_dir(name), device="cuda" if torch.cuda.is_available() else "cpu"
        )
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._model.encode(texts, normalize_embeddings=True, batch_size=16).tolist()


def _model_dir(name: str) -> str:
    from pathlib import Path

    if Path(name).exists():
        return name
    try:
        from huggingface_hub import snapshot_download

        return snapshot_download(name, local_files_only=True)
    except Exception:
        return name


def get_embedder():
    from app.config import get_settings

    provider = get_settings().embedding_provider
    if provider == "bge-m3":
        return BGEEmbedder()
    raise ValueError(f"未知 embedding_provider: {provider}")

