"""Contract text preprocessor — unified LLM call for OCR cleanup + party identification.

Replaces three scattered steps (text cleanup, party hints, quality check) with
one LLM call that outputs cleaned text, identified parties, quality markers, and
a human-auditable list of corrections.

Called by the document parsing pipeline BEFORE timeline extraction and clause
classification, so downstream consumers always see cleaned text.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_PREPROCESS_CHUNK_SIZE = 3600


def _normalize_contract_text(text: str) -> str:
    """Preserve contract structure while normalizing line noise."""
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    lines: list[str] = []
    blank_run = 0
    for raw_line in value.split("\n"):
        line = re.sub(r"[ \t\f\v]+", " ", raw_line).strip()
        if not line:
            blank_run += 1
            if blank_run <= 1:
                lines.append("")
            continue
        blank_run = 0
        lines.append(line)
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _split_preprocess_chunks(text: str, max_chars: int = _PREPROCESS_CHUNK_SIZE) -> list[str]:
    """Split cleaned contract text into paragraph-aligned chunks."""
    normalized = _normalize_contract_text(text)
    if len(normalized) <= max_chars:
        return [normalized] if normalized else []

    chunks: list[str] = []
    buffer: list[str] = []
    buffer_len = 0
    paragraphs = re.split(r"\n{2,}", normalized)
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        pieces = [paragraph]
        if len(paragraph) > max_chars:
            pieces = []
            start = 0
            while start < len(paragraph):
                end = min(len(paragraph), start + max_chars)
                pieces.append(paragraph[start:end])
                start = end
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            extra = len(piece) + (2 if buffer else 0)
            if buffer and buffer_len + extra > max_chars:
                chunks.append("\n\n".join(buffer))
                buffer = [piece]
                buffer_len = len(piece)
            else:
                buffer.append(piece)
                buffer_len += extra
    if buffer:
        chunks.append("\n\n".join(buffer))
    return chunks


def _deterministic_ocr_fix(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Apply conservative, auditable OCR repairs before LLM cleanup."""
    cleaned_lines: list[str] = []
    corrections: list[dict[str, Any]] = []
    for index, raw_line in enumerate(_normalize_contract_text(text).split("\n")):
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        if any(term in line for term in (
            "中华人民共和国科学技术部印制", "填写说明", "示范文本", "技术合同登记机构",
        )) and len(line) <= 80:
            corrections.append({
                "original": line,
                "corrected": "",
                "position": index,
                "reason": "template-noise",
            })
            continue
        repaired = re.sub(r"[|]{2,}", " ", line)
        repaired = re.sub(r"\s{2,}", " ", repaired).strip()
        if repaired != line:
            corrections.append({
                "original": line,
                "corrected": repaired,
                "position": index,
                "reason": "normalize-spacing-or-noise",
            })
        cleaned_lines.append(repaired)
    cleaned_text = "\n".join(cleaned_lines).strip()
    return cleaned_text, corrections

# ── System prompt ──────────────────────────────────────────────────────

_PREPROCESS_SYSTEM_PROMPT = """\
你是一个中文合同文档 OCR 修复与主体识别助手。输入文本来自 PDF 扫描件提取，
通常包含 OCR 错误、排版错位、页眉页脚噪音和非标准主体称谓。

你需要**主动修复明显 OCR 错误**并输出一个 JSON 对象。

## 中文合同高频术语参考（用于 OCR 修复推断）

工程/采购合同最常见的词汇（按出现频率排列）：
质保金、质保期、届满、竣工验收、工程完工证书、投产、违约金、
合同总价、合同价款、预付款、进度款、结算款、发票、增值税、
勘察设计、可行性研究、初步设计、施工图设计、竣工图、
发包人、承包人、承包商、分包商、监理、项目经理、
不可抗力、终止、解除、续签、续约、争议解决、仲裁、
保密、知识产权、数据保护、隐私、合规、安全生产、环境保护、
缺陷责任期、保修期、维护期、技术服务、技术咨询、培训、
交货、验收、签收、安装、调试、试运行、投产运行。

## 任务 1：文本清洗——主动修复模式

1. **必须修复**的 OCR 错误模式（从上下文可明确推断）：
   - 形近字："盒→金"(质保盒→质保金)、"血→届/期"(届满/期间)、
     "曰→日"、"己→已"、"人→入/八"、"尿→承/建"(承建商/承包商)、
     "止→正"、"白→的/自"、"全→金"、"干→千/于"
   - 中英文混入乱码块：如 "liEI"、"JFIII"、"除司|"、"jI"等，
     如果周围有可读中文上下文，删除或根据上下文推断修正
   - 换行切断的句子合并
   - 页眉页脚噪音删除

2. **不确定的修正**（上下文不足时）：保留原文并在 corrections 中标注为 low-confidence
3. **保持数字、日期、金额、百分比不变**——这是法律要约
4. 合并被硬换行切断的合同标题行（例如第一行是项目名称、第二行是合同类型）

## 任务 2：主体识别

工程/采购合同主体称谓：
- 甲方侧：业主、发包方、委托方、采购方、买方、需方、定作方、招标人、建设方
- 乙方侧：承包方、承包商、设计方、施工方、供应商、受托方、卖方、供方、承揽方、监理方、勘察方

输出：
- label: 原文称谓
- fullName: 完整企业名称
- role: A（甲方/付款方）或 B（乙方/服务方）
- confidence: 0-1

## 任务 3：质量标记

- 标记非中文字符 > 40% 的段落
- 标记疑似缺页
- overall: GOOD / FAIR / POOR

## JSON 输出格式

{
  "cleanedText": "完整清洗后文本",
  "parties": [{"label": "原文称谓", "fullName": "全称", "role": "A", "confidence": 0.95}],
  "quality": {"overall": "GOOD", "garbledSections": []},
  "corrections": [{"original": "原文", "corrected": "修正", "position": 0, "reason": "OCR形近字，上下文确认"}]
}

## 关键约束

- 金额、日期、百分比、合同编号**绝对不能改**
- 明显 OCR 错误积极修正，模糊的标记为 low-confidence
- 不确定的修正保留原文，不要强行猜测
- cleanedText 必须完整不能截断
- parties 只输出可从原文识别的实体，不臆造
"""


class ContractTextPreprocessor:
    """Unified contract text preprocessing: OCR cleanup + party identification.

    Usage::

        preprocessor = ContractTextPreprocessor(llm_service)
        result = preprocessor.process(raw_text, file_name)
        # result.cleaned_text → cleaned full text
        # result.parties → [{label, fullName, role, confidence}]
        # result.quality → {overall, garbledSections}
        # result.corrections → [{original, corrected, position, reason}]
    """

    def __init__(self, llm_service):  # LLMService
        self._llm = llm_service

    def process(self, raw_text: str, file_name: str = "") -> PreprocessResult:
        """Run unified preprocessing on raw contract text.

        Two-phase: deterministic OCR fix first, then LLM semantic polish.
        Returns a PreprocessResult. On LLM failure, still returns deterministically-cleaned text.
        """
        text = _normalize_contract_text(raw_text)
        if len(text) < 100:
            logger.warning("Contract text too short (%d chars), skipping preprocess", len(text))
            return PreprocessResult(
                cleaned_text=text,
                parties=[],
                quality={"overall": "POOR", "garbledSections": []},
                corrections=[],
                llm_used=False,
            )

        # ── Phase 1: Deterministic OCR cleanup (no LLM) ──
        det_text, det_corrections = _deterministic_ocr_fix(text)
        logger.info(
            "Deterministic OCR fix: %d corrections applied", len(det_corrections),
        )

        try:
            data = self._clean_with_llm(det_text, file_name)
        except Exception as exc:
            logger.warning("Contract preprocess LLM failed after retries, returning deterministic text: %s", exc)
            return PreprocessResult(
                cleaned_text=det_text or text,
                parties=[],
                quality={"overall": "FAIR", "garbledSections": [], "error": str(exc)[:200]},
                corrections=det_corrections,
                llm_used=False,
            )

        cleaned_text = str(data.get("cleanedText") or det_text or text).strip() or det_text or text
        return PreprocessResult(
            cleaned_text=cleaned_text,
            parties=self._normalize_parties(data.get("parties") or []),
            quality=data.get("quality") or {"overall": "FAIR", "garbledSections": []},
            corrections=list(det_corrections) + list(data.get("corrections") or []),
            llm_used=True,
        )

    @staticmethod
    def _parse_response(content: str) -> dict[str, Any]:
        """Parse LLM JSON response with fallback repair."""
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # Strip markdown fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", content)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse preprocessor response: %.200s", content)
            return {}

    @staticmethod
    def _normalize_parties(raw: list[dict]) -> list[dict]:
        """Normalize and validate party entries."""
        result = []
        seen = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            full_name = str(item.get("fullName") or "").strip()
            if not full_name or full_name in seen:
                continue
            seen.add(full_name)
            role = str(item.get("role") or "").upper()
            if role not in ("A", "B"):
                role = ""
            confidence = float(item.get("confidence", 0))
            result.append({
                "label": str(item.get("label") or "").strip(),
                "fullName": full_name,
                "role": role,
                "confidence": min(max(confidence, 0.0), 1.0),
            })
        return result

    def _clean_with_llm(self, det_text: str, file_name: str) -> dict[str, Any]:
        """Run chunked LLM cleanup so long OCR text never truncates."""
        chunks = _split_preprocess_chunks(det_text, _PREPROCESS_CHUNK_SIZE)
        if not chunks:
            raise ValueError("No preprocess chunks available")

        cleaned_chunks: list[str] = []
        parties: list[dict[str, Any]] = []
        corrections: list[dict[str, Any]] = []
        quality_levels: list[str] = []

        for index, chunk in enumerate(chunks):
            payload = {
                "fileName": file_name,
                "chunkIndex": index + 1,
                "chunkCount": len(chunks),
                "textLength": len(det_text),
                "chunkLength": len(chunk),
                "rawText": chunk,
            }
            response = self._llm._call_llm_with_retry(
                lambda payload=payload: self._llm.analysis_client.chat.completions.create(
                    model=self._llm.model,
                    messages=[
                        {"role": "system", "content": _PREPROCESS_SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0.0,
                    max_tokens=4096,
                    response_format={"type": "json_object"},
                    stream=False,
                ),
                max_retries=2,
                backoff_base=1.0,
            )
            content = response.choices[0].message.content if response.choices else ""
            data = self._parse_response(content or "{}")
            cleaned_chunk = str(data.get("cleanedText") or "").strip()
            if not cleaned_chunk:
                raise ValueError(f"LLM chunk {index + 1} returned empty cleanedText")
            cleaned_chunks.append(cleaned_chunk)
            parties.extend(self._normalize_parties(data.get("parties") or []))
            corrections.extend([
                item for item in data.get("corrections") or []
                if isinstance(item, dict)
            ])
            quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
            quality_levels.append(str(quality.get("overall") or "FAIR").upper())

        overall = "GOOD"
        if any(level == "POOR" for level in quality_levels):
            overall = "POOR"
        elif any(level == "FAIR" for level in quality_levels):
            overall = "FAIR"

        return {
            "cleanedText": "\n\n".join(chunk.strip() for chunk in cleaned_chunks if chunk.strip()).strip(),
            "parties": parties,
            "quality": {"overall": overall, "garbledSections": []},
            "corrections": corrections,
        }


class PreprocessResult:
    """Result of contract text preprocessing."""

    __slots__ = (
        "cleaned_text", "parties", "quality",
        "corrections", "llm_used",
    )

    def __init__(
        self,
        cleaned_text: str,
        parties: list[dict],
        quality: dict,
        corrections: list[dict],
        llm_used: bool = False,
    ):
        self.cleaned_text = cleaned_text
        self.parties = parties
        self.quality = quality
        self.corrections = corrections
        self.llm_used = llm_used

    @property
    def quality_overall(self) -> str:
        return str(self.quality.get("overall") or "FAIR").upper()

    @property
    def has_parties(self) -> bool:
        return len(self.parties) > 0

    @property
    def has_corrections(self) -> bool:
        return len(self.corrections) > 0

    def party_hints(self) -> dict[str, str]:
        """Convert identified parties to intake-extractor-compatible hints."""
        hints: dict[str, str] = {}
        for party in self.parties:
            role = party.get("role", "")
            name = party.get("fullName", "")
            if role == "A":
                hints["partyA"] = name
            elif role == "B":
                hints["partyB"] = name
        return hints

    def to_dict(self) -> dict:
        return {
            "cleanedText": self.cleaned_text,
            "parties": self.parties,
            "quality": self.quality,
            "corrections": self.corrections,
            "llmUsed": self.llm_used,
        }
