"""Validated, serializable pipeline configuration."""
from dataclasses import asdict, dataclass
import os
import math


@dataclass(frozen=True)
class Config:
    sample_rate: int = 22050
    confidence_threshold: float = 70.0
    workers: int = min(4, os.cpu_count() or 1)
    timeout: float = 3600.0
    fps: str = "25"
    keep_temp: bool = False
    min_overlap: float = 1.0

    def __post_init__(self):
        if type(self.sample_rate) is not int or type(self.workers) is not int:
            raise ValueError("sample_rate and workers must be integers")
        if type(self.keep_temp) is not bool:
            raise ValueError("keep_temp must be a boolean")
        if any(type(v) not in (int, float) for v in (self.timeout, self.min_overlap, self.confidence_threshold)):
            raise ValueError("timeout, min_overlap and confidence threshold must be numbers, not booleans")
        if self.sample_rate not in (11025, 22050):
            raise ValueError("sample_rate must be 11025 or 22050")
        if not 0 <= self.confidence_threshold <= 100:
            raise ValueError("confidence threshold must be between 0 and 100")
        if not 1 <= self.workers <= 64:
            raise ValueError("workers must be between 1 and 64")
        if not all(math.isfinite(v) and v > 0 for v in (self.timeout, self.min_overlap)):
            raise ValueError("timeout and min_overlap must be finite and positive")

    def to_dict(self):
        return asdict(self)
