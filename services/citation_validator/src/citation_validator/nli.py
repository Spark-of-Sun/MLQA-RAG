"""V6 entailment with a pinned NLI cross-encoder (blueprint 11.6, D15, G7.3, G7.4).

Deterministic by construction: CPU inference with ONNX Runtime (one intra-op thread, sequential execution, no
graph optimizations that reorder floating-point work), weights verified against `NLI_MODEL_HASH` (SHA-256 of the
ONNX file) before the first use, fixed thresholds. The default model is an ONNX export of
`cross-encoder/nli-deberta-v3-small` (candidate in blueprint 4.5); the label order is read from the model's own
config.json, never assumed.

A sentence is supported when, for at least one cited chunk, P(entailment) >= `threshold` and P(contradiction) is
below `contradiction_max`. The threshold is calibrated on a human-labeled set (precision of "supported" >= 0.99,
G7.3) and recorded in eval/floors.toml; until then the strict default stands.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_REPO = "Xenova/nli-deberta-v3-small"
DEFAULT_FILE = "onnx/model.onnx"
DEFAULT_THRESHOLD = 0.90
DEFAULT_CONTRADICTION_MAX = 0.10
MAX_TOKENS = 512


class NliUnavailableError(RuntimeError):
    """Model missing or hash mismatch: V6 fails closed (no sentence passes on V6)."""


@dataclass(frozen=True)
class NliScore:
    entailment: float
    contradiction: float
    neutral: float


def _softmax(logits: list[float]) -> list[float]:
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    total = sum(exps)
    return [e / total for e in exps]


class NliModel:
    def __init__(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        cache_dir: Path,
        *,
        repo: str = DEFAULT_REPO,
        filename: str = DEFAULT_FILE,
        expected_sha256: str | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        contradiction_max: float = DEFAULT_CONTRADICTION_MAX,
    ) -> None:
        self._cache_dir = cache_dir
        self._repo = repo
        self._file = filename
        self._expected = expected_sha256
        self.threshold = threshold
        self.contradiction_max = contradiction_max
        self._session = None
        self._tokenizer = None
        self._labels: dict[str, int] = {}
        self._lock = threading.Lock()
        self.weights_sha256: str | None = None

    def _load(self) -> None:
        with self._lock:
            if self._session is not None:
                return
            try:
                import onnxruntime as ort
                from huggingface_hub import hf_hub_download
                from tokenizers import Tokenizer
            except ImportError as exc:
                raise NliUnavailableError(
                    "onnxruntime, tokenizers and huggingface_hub are required"
                ) from exc
            model_path = Path(
                hf_hub_download(self._repo, self._file, cache_dir=str(self._cache_dir))
            )
            digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
            if self._expected and digest != self._expected:
                raise NliUnavailableError("NLI weights do not match NLI_MODEL_HASH")
            self.weights_sha256 = digest
            config = json.loads(
                Path(
                    hf_hub_download(self._repo, "config.json", cache_dir=str(self._cache_dir))
                ).read_text(encoding="utf-8")
            )
            id2label = {int(k): v.lower() for k, v in config["id2label"].items()}
            self._labels = {label: idx for idx, label in id2label.items()}
            if not {"entailment", "contradiction"} <= set(self._labels):
                raise NliUnavailableError(f"unexpected NLI labels {sorted(self._labels)}")
            tok = Tokenizer.from_file(
                hf_hub_download(self._repo, "tokenizer.json", cache_dir=str(self._cache_dir))
            )
            tok.enable_truncation(max_length=MAX_TOKENS)
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
            self._session = ort.InferenceSession(
                str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
            )
            self._tokenizer = tok
            log.info("NLI model loaded (sha256 %s…)", digest[:12])

    def score(self, premise: str, hypothesis: str) -> NliScore:
        self._load()
        assert self._tokenizer is not None and self._session is not None
        import numpy as np

        enc = self._tokenizer.encode(premise, hypothesis)
        feeds = {
            "input_ids": np.array([enc.ids], dtype=np.int64),
            "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
        }
        names = {i.name for i in self._session.get_inputs()}
        if "token_type_ids" in names:
            feeds["token_type_ids"] = np.array([enc.type_ids], dtype=np.int64)
        logits = self._session.run(None, {k: v for k, v in feeds.items() if k in names})[0][
            0
        ].tolist()
        probs = _softmax([float(x) for x in logits])
        neutral = self._labels.get("neutral")
        return NliScore(
            entailment=probs[self._labels["entailment"]],
            contradiction=probs[self._labels["contradiction"]],
            neutral=probs[neutral] if neutral is not None else 0.0,
        )

    def supported(self, premises: list[str], hypothesis: str) -> tuple[bool, float]:
        """(supported, best entailment probability) over the cited chunks."""
        best = 0.0
        for premise in premises:
            s = self.score(premise, hypothesis)
            best = max(best, s.entailment)
            if s.entailment >= self.threshold and s.contradiction < self.contradiction_max:
                return True, s.entailment
        return False, best
