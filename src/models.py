"""Core data models for clinical document processing."""

from dataclasses import dataclass, field
from typing import List, Optional

from src.preprocessing import TextWindow, TokenOffset


@dataclass
class Line:
    """Represents a single line in a clinical document."""
    text: str
    start: int  # Character offset in raw text
    end: int    # Character offset in raw text
    line_kind: str  # header, subheader, key_value, bullet, free_text, continuation
    line_id: int = 0
    key: Optional[str] = None
    value: Optional[str] = None
    section_type: Optional[str] = None
    subsection_type: Optional[str] = None


@dataclass
class Section:
    """Represents a section in a clinical document."""
    section_type: str
    text: str
    start: int  # Character offset in raw text
    end: int    # Character offset in raw text
    level: int = 1  # 1 for main section, 2 for subsection
    parent_section_type: Optional[str] = None
    lines: List[Line] = field(default_factory=list)
    confidence: float = 1.0
    line_id: Optional[int] = None
    alias_source: Optional[str] = None


@dataclass
class ClinicalDocument:
    """Represents a complete clinical document."""
    file_id: str
    raw_text: str
    normalized_text: str = ""
    norm_to_raw_map: List[int] = field(default_factory=list)
    raw_to_norm_map: List[int] = field(default_factory=list)
    line_windows: List[TextWindow] = field(default_factory=list)
    sentence_windows: List[TextWindow] = field(default_factory=list)
    model_windows: List[TextWindow] = field(default_factory=list)
    token_offsets: List[TokenOffset] = field(default_factory=list)
    sections: List[Section] = field(default_factory=list)
    lines: List[Line] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    
    def __post_init__(self):
        """Calculate metadata after initialization."""
        existing_metadata = dict(self.metadata)
        self.metadata = {
            'char_len': len(self.raw_text),
            'line_count': len(self.raw_text.splitlines())
        }
        self.metadata.update(existing_metadata)


@dataclass
class SpanCandidate:
    """Represents a candidate medical concept span."""
    file_id: str
    text: str
    start: int  # Character offset in raw text
    end: int    # Character offset in raw text
    type_candidate: str  # TRIỆU_CHỨNG, TÊN_XÉT_NGHIỆM, KẾT_QUẢ_XÉT_NGHIỆM, CHẨN_ĐOÁN, THUỐC
    section_type: Optional[str] = None
    subsection_type: Optional[str] = None
    line_id: Optional[int] = None
    line_text: Optional[str] = None
    left_context: str = ""
    right_context: str = ""
    time_context: str = "unknown"  # past, recent_past, current, in_hospital, unknown
    source: List[str] = field(default_factory=list)  # dictionary, regex, section_rule, etc.
    confidence: float = 0.0
    assertion_candidates: List[str] = field(default_factory=list)  # isNegated, isHistorical, isFamily
    mapping_candidates: List[str] = field(default_factory=list)  # ICD or RxNorm codes
    should_output: bool = True
    span_status: str = "candidate"  # candidate, accepted, rejected, needs_review
    reject_reason: Optional[str] = None
    notes: str = ""


@dataclass
class EntityOutput:
    """Final entity output format for submission."""
    text: str
    position: List[int]  # [start, end]
    type: str
    assertions: List[str]
    candidates: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        result = {
            "text": self.text,
            "position": self.position,
            "type": self.type,
            "assertions": self.assertions
        }
        # Only include candidates for CHẨN_ĐOÁN and THUỐC
        if self.type in ["CHẨN_ĐOÁN", "THUỐC"]:
            result["candidates"] = self.candidates
        return result
