"""
GPU detection — checks for CUDA/MPS availability on startup.

Results are cached and exposed via GET /system/capabilities.
Used to route PDF ingestion (MinerU needs GPU, Marker works on CPU).
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger("vanilla.gpu_detect")


@dataclass
class GPUCapabilities:
    gpu: bool
    gpu_type: str  # "cuda" | "mps" | "none"


_cached: GPUCapabilities | None = None


def detect_gpu() -> GPUCapabilities:
    """
    Detect GPU availability. Caches result after first call.

    Checks for:
    1. CUDA (NVIDIA GPUs) via torch.cuda
    2. MPS (Apple Silicon) via torch.backends.mps
    3. Falls back to "none" if no GPU or torch not installed
    """
    global _cached
    if _cached is not None:
        return _cached

    try:
        import torch

        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            logger.info("CUDA GPU detected: %s", gpu_name)
            _cached = GPUCapabilities(gpu=True, gpu_type="cuda")
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            logger.info("Apple MPS GPU detected")
            _cached = GPUCapabilities(gpu=True, gpu_type="mps")
        else:
            logger.info("No GPU detected (torch installed but no CUDA/MPS)")
            _cached = GPUCapabilities(gpu=False, gpu_type="none")
    except ImportError:
        logger.info("PyTorch not installed — GPU detection skipped, assuming CPU-only")
        _cached = GPUCapabilities(gpu=False, gpu_type="none")

    return _cached
