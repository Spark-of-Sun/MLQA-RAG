"""The pinned entailment model (doc 11.6, 4.5). NOT executed in the 2 GB build sandbox.

A DeBERTa-v3 NLI cross-encoder on CPU with a fixed thread count and deterministic kernels, so the
same input gives the same score after any restart. The weights file is hashed at load and compared
with ``NLI_MODEL_HASH``; a mismatch refuses to start, so a swapped model can never change verdicts
silently. ``transformers`` and ``torch`` are an optional install (``citation-validator[nli]``).
The threshold is a calibration result (gate G7.3, human-labelled pairs) and must not be guessed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from typing import Any

DEFAULT_MODEL: Final = "cross-encoder/nli-deberta-v3-small"
_MAX_LENGTH: Final = 512


class ModelHashMismatchError(RuntimeError):
    """The model weights are not the pinned ones; the validator must not start."""


def file_sha256(path: Path) -> str:
    """Streaming SHA-256 of a weights file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class TransformersNliScorer:
    """Entailment probability from a Hugging Face sequence-classification NLI model."""

    def __init__(self, model_name: str = DEFAULT_MODEL, expected_sha256: str | None = None) -> None:
        """Load the model, verify the pinned weights hash and fix determinism settings."""
        import torch  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        from huggingface_hub import hf_hub_download  # noqa: PLC0415
        from transformers import (  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(mode=True)
        weights = Path(hf_hub_download(model_name, "model.safetensors"))
        actual = file_sha256(weights)
        if expected_sha256 and actual != expected_sha256.lower():
            msg = f"NLI weights hash {actual} does not match the pinned {expected_sha256}"
            raise ModelHashMismatchError(msg)
        self.model_id = f"{model_name}@{actual[:12]}"
        self.weights_sha256 = actual
        self._torch: Any = torch
        self._tokenizer: Any = AutoTokenizer.from_pretrained(model_name)
        self._model: Any = AutoModelForSequenceClassification.from_pretrained(model_name).eval()
        labels = {int(i): str(v).lower() for i, v in self._model.config.id2label.items()}
        self._entail = next(i for i, name in labels.items() if "entail" in name)

    def entailment(self, premise: str, hypothesis: str) -> float:
        """Probability that ``premise`` entails ``hypothesis`` (batch of one, CPU, no sampling)."""
        encoded = self._tokenizer(
            premise, hypothesis, truncation=True, max_length=_MAX_LENGTH, return_tensors="pt"
        )
        with self._torch.no_grad():
            logits = self._model(**encoded).logits[0]
        return float(self._torch.softmax(logits, dim=-1)[self._entail])
