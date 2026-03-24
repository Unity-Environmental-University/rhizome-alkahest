"""Edge — the atom."""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Edge:
    subject: str
    predicate: str
    object: str
    confidence: float = 0.7
    phase: str = "fluid"
    observer: str = ""
    notes: str = ""
    id: Optional[str] = None
    created_at: Optional[datetime] = None
    slug: Optional[str] = None
    hash: Optional[str] = None

    @property
    def triple(self) -> tuple[str, str, str]:
        return (self.subject, self.predicate, self.object)

    def __repr__(self):
        return f"({self.subject} --{self.predicate}--> {self.object}) [{self.confidence:.2f}]"
