"""Load SoldierIQ's decision model, int8 weight-only (torchao), from its HF repo.

Default: d1-omni-600M fine-tuned on colour + presence questions (training/colour/). The untrained base is
Keshav069/d1-omni-600m-int8 (same files and loading), selectable with MODEL_REPO.

The repo holds pytorch_model.bin with torchao Int8Tensor weights (safetensors can't hold them) plus
Liquid's model code. Loading: build the model shape from config (no weights read), quantize it the same
way so the shapes match, then load the int8 weights into it.
"""
from __future__ import annotations

import os
from pathlib import Path

import torch

MODEL_REPO = os.environ.get("MODEL_REPO", "Keshav069/soldieriq-decide-600m-colour-int8")
MODEL_NAME = "soldieriq/decide-600m-colour-int8"


def download(repo: str = MODEL_REPO) -> Path:
    if Path(repo).is_dir():  # a local folder with the same files (e.g. a model we just built)
        return Path(repo)
    from huggingface_hub import snapshot_download

    # HF_TOKEN (env) is needed because the repo is private; a local `hf auth login` works too.
    return Path(snapshot_download(repo, allow_patterns=["*.py", "*.json", "pytorch_model.bin", "LICENSE"],
                                  ignore_patterns=["__pycache__/*", "load_int8.py"]))


def load(path: Path | None = None):
    from torchao.quantization import Int8WeightOnlyConfig, quantize_
    from transformers import AutoConfig, AutoModel

    path = path or download()
    cfg = AutoConfig.from_pretrained(path, trust_remote_code=True)
    model = AutoModel.from_config(cfg, trust_remote_code=True, dtype=torch.float32)
    quantize_(model, Int8WeightOnlyConfig())
    state = torch.load(path / "pytorch_model.bin", weights_only=False, map_location="cpu")
    missing, unexpected = model.load_state_dict(state, strict=False)
    if unexpected:
        raise RuntimeError(f"unexpected weights in {path}: {unexpected[:5]}")
    if missing:
        raise RuntimeError(f"weights missing from {path}: {missing[:5]}")
    return model.eval()
