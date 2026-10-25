"""Rung 2 semantic claim filter using climatebert/environmental-claims."""
import logging
import warnings

logger = logging.getLogger(__name__)

MODEL_NAME = "climatebert/environmental-claims"
_MODEL = None
_TOKENIZER = None
_DEVICE = None
_LOAD_FAILED = False


def _get_device(torch_mod):
    """Select the execution device automatically in order: mps, cuda, cpu."""
    if hasattr(torch_mod.backends, "mps") and torch_mod.backends.mps.is_available():
        return torch_mod.device("mps")
    if torch_mod.cuda.is_available():
        return torch_mod.device("cuda")
    return torch_mod.device("cpu")


def _load_model():
    """Lazily load the tokenizer and model on the best available device."""
    global _MODEL, _TOKENIZER, _DEVICE, _LOAD_FAILED
    if _LOAD_FAILED:
        return None, None, None
    if _MODEL is not None and _TOKENIZER is not None:
        return _MODEL, _TOKENIZER, _DEVICE

    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        device = _get_device(torch)
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        model.to(device)
        model.eval()

        _MODEL = model
        _TOKENIZER = tokenizer
        _DEVICE = device
        return _MODEL, _TOKENIZER, _DEVICE
    except Exception as exc:
        _LOAD_FAILED = True
        warnings.warn(f"Semantic filter model '{MODEL_NAME}' unavailable: {exc}")
        return None, None, None


def _reset_model():
    """Reset cached model state (for tests)."""
    global _MODEL, _TOKENIZER, _DEVICE, _LOAD_FAILED
    _MODEL = None
    _TOKENIZER = None
    _DEVICE = None
    _LOAD_FAILED = False


def classify_sentence(text: str, threshold: float = 0.05) -> tuple[bool, float]:
    """Classify a sentence using climatebert/environmental-claims.

    Returns (verdict, probability). If the model or weights are unavailable,
    returns (False, 0.0) with a warning.
    """
    import os
    if os.environ.get("GCT_DISABLE_SEMANTIC") == "1":
        return False, 0.0

    if not text or not text.strip():
        return False, 0.0

    model, tokenizer, device = _load_model()
    if model is None or tokenizer is None:
        return False, 0.0

    try:
        import torch

        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        if device is not None:
            inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)
            logits = outputs.logits
            probs = torch.softmax(logits, dim=-1)[0]

        claim_idx = 1
        if hasattr(model, "config") and hasattr(model.config, "label2id") and model.config.label2id:
            for name, idx in model.config.label2id.items():
                if str(name).lower() in ("yes", "claim", "environmental", "true"):
                    claim_idx = idx
                    break

        prob = float(probs[claim_idx].item())
        verdict = bool(prob >= threshold)
        return verdict, prob
    except Exception as exc:
        warnings.warn(f"Failed to classify sentence: {exc}")
        return False, 0.0
