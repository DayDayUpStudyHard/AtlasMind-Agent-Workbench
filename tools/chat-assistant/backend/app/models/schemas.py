from pydantic import BaseModel, Field
from typing import List, Optional


class ChatMessage(BaseModel):
    role: str       # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = Field(default_factory=list)
    topK: int = Field(default=5, ge=1, le=20)


class SourceCitation(BaseModel):
    id: int
    title: str
    snippet: str


class SSEChunk(BaseModel):
    type: str          # "chunk" | "sources" | "done" | "error"
    content: Optional[str] = None
    sources: Optional[List[SourceCitation]] = None
    error: Optional[str] = None


class SuggestionResponse(BaseModel):
    suggestions: List[str]


class KbIngestRequest(BaseModel):
    documentId: int
    jobId: int
    spaceId: int
    title: str
    filePath: str
    fileType: str
    parseMode: str = "OCR"


class KbReindexRequest(BaseModel):
    documentId: int
    jobId: int


class KbQaRequest(BaseModel):
    message: str
    spaceId: Optional[int] = None
    documentId: Optional[int] = None
    includeArticles: bool = True
    topK: int = Field(default=5, ge=1, le=20)
