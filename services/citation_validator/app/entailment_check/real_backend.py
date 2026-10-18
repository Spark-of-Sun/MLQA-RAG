from __future__ import annotations

import os


class CrossEncoderEntailmentChecker:
    """Real backend — a lightweight cross-encoder NLI model scoring
    whether chunk_text entails claim_sentence, per docs/architecture.md §5.
    Lazily imports sentence-transformers/torch so this module can be
    imported without the 'real' extra installed.
    """

    def __init__(self, model_name: str | None = None, device: str | None = None):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "CrossEncoderEntailmentChecker requires the 'real' extra: pip install -e '.[real]'"
            ) from exc

        self._model = CrossEncoder(
            model_name or os.environ.get("ENTAILMENT_MODEL", "cross-encoder/nli-deberta-v3-base"),
            device=device or os.environ.get("ENTAILMENT_DEVICE", "cpu"),
        )

    def score(self, claim_sentence: str, chunk_text: str) -> float:
        import torch

        logits = self._model.predict([(chunk_text, claim_sentence)])
        # This checkpoint family outputs (contradiction, entailment, neutral)
        # logits in that order — softmax and take the entailment probability.
        probs = torch.softmax(torch.tensor(logits), dim=-1)[0]
        return float(probs[1])
