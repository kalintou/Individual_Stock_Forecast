"""
Fusion module: evidence conversion, validation, and merging.

This package converts outputs from frontend and tools into unified EvidenceItem
objects, validates their quality, and manages the evidence lifecycle.
"""

from fusion.base import BaseFusion
from fusion.simple_fusion import SimpleFusion

__all__ = [
    "BaseFusion",
    "SimpleFusion",
]
