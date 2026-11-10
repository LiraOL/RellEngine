"""Rell Engine: generador de objetos mágicos y no mágicos para D&D 5e."""
from .engine import Engine, GenerationError, render_text
from .export import export_payload

__version__ = "2.0.0"
__all__ = ["Engine", "GenerationError", "render_text", "export_payload", "__version__"]
