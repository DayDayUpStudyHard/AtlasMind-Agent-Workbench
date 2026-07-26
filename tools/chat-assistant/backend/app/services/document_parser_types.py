"""Shared parser data types."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParsedBlock:
    text: str
    section_title: str = ""
    source_page: int | None = None


@dataclass
class Chunk:
    text: str
    section_title: str = ""
    source_page: int | None = None
