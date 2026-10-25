"""Auditor Greenwashing Copilot & Candidate Scanner (Story M1-5.5, FR39).

Evaluates qualitative claims against report evidence using the EmeraldMind 4-type
taxonomy and strict responsible abstention rules.

Invariants:
1. FR39: GCT never assigns greenwashing flags automatically. All evaluations
   produce unreviewed candidates for human auditor review.
2. 4-Type Taxonomy:
   - Type 1: Factually false or unaccredited environmental labels/certifications.
   - Type 2: Regulatory/statutory obligations framed as voluntary initiatives.
   - Type 3: Boundary mismatch / partial truth presented as whole.
   - Type 4: Direct factual contradictions against reported evidence.
3. Strict Abstention: Ambition, tone, or lack of evidence strictly warrants
   abstain. Tone-based accusations are forbidden.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

GREENWASHING_TYPES = ("Type 1", "Type 2", "Type 3", "Type 4")
AUDIT_VERDICTS = ("verified", "greenwashing", "abstain")

AUDIT_PROMPT_TEMPLATE = """You are an ESG and Greenwashing Fact-Checker for GoCarbonTracker.

Task: Given an ESG-related claim and report context, fact-check it and determine whether it constitutes greenwashing, verified, or if you should abstain.

### Fact-Checking Process:
- Use the provided context as your PRIMARY source of truth.
- Your decision MUST be based on verifiable facts that prove or disprove the claim.
- NEVER judge based on:
  * Vague wording or marketing language
  * How suspicious or ambitious a claim sounds
  * Absence of detail (warrants abstain, not greenwashing)
  * Intuition about what could be misleading

### Decision Criteria:
1. Greenwashing: Specific evidence that the claim is factually false or misleading:
   - Type 1 (Factually false labels / certifications): The certification/label is false, unaccredited, or misrepresents standards.
   - Type 2 (Legal obligations misrepresented as voluntary): The action is legally mandated by statute, not a voluntary initiative.
   - Type 3 (Partial truth / boundary overgeneralization): Only part of the operations/fleet/product meets the stated criteria, or organizational boundary is misrepresented.
   - Type 4 (Factual contradiction): Retrieved evidence directly contradicts the assertion.

2. Verified: Verifiable evidence in the context explicitly confirms the claim.

3. Abstain: Insufficient or missing evidence in the context to verify or refute the claim. Zero tone-based accusations permitted.

### OUTPUT FORMAT:
Label: <verified / greenwashing / abstain>
Type: <Type 1 / Type 2 / Type 3 / Type 4 / None>
Justification: <Quote specific passages and explain how they prove/disprove the claim. If abstaining, state what information is missing.>
"""


def format_qualitative_audit_prompt(
    claim_text: str, contexts: Optional[List[Any]] = None
) -> str:
    """Format prompt for qualitative greenwashing audit based on EmeraldMind."""
    ctx_str = ""
    if contexts:
        snippets = []
        for c in contexts:
            if isinstance(c, dict):
                snippets.append(c.get("content", str(c)))
            else:
                snippets.append(str(c))
        ctx_str = "\n---\n".join(snippets)

    return f"""{AUDIT_PROMPT_TEMPLATE}

<CONTEXT>
{ctx_str or '[No supporting context provided]'}
</CONTEXT>

<CLAIM>
{claim_text}
</CLAIM>

<OUTPUT>
Label:
Type:
Justification:
</OUTPUT>"""


def parse_audit_response(raw_text: str) -> Dict[str, Any]:
    """Parse raw LLM response into structured audit record."""
    verdict = "abstain"
    gw_type = None
    justification = ""

    lines = raw_text.strip().splitlines()
    for line in lines:
        line_clean = line.strip()
        if line_clean.lower().startswith("label:"):
            val = line_clean.split(":", 1)[1].strip().lower()
            if "greenwashing" in val:
                verdict = "greenwashing"
            elif "verified" in val or "not_greenwashing" in val:
                verdict = "verified"
            else:
                verdict = "abstain"
        elif line_clean.lower().startswith("type:"):
            val = line_clean.split(":", 1)[1].strip()
            for t in GREENWASHING_TYPES:
                if t.lower() in val.lower():
                    gw_type = t
                    break
        elif line_clean.lower().startswith("justification:"):
            justification = line_clean.split(":", 1)[1].strip()

    if not justification and "justification:" in raw_text.lower():
        idx = raw_text.lower().find("justification:")
        justification = raw_text[idx + len("justification:") :].strip()

    missing_reason = None
    if verdict == "abstain":
        gw_type = None
        missing_reason = justification or "Insufficient context to verify or refute claim."

    return {
        "verdict": verdict,
        "greenwashing_type": gw_type,
        "justification": justification,
        "missing_evidence_reason": missing_reason,
    }


def audit_claim(
    claim_text: str,
    contexts: Optional[List[Any]] = None,
    llm_fn: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """Audit a qualitative claim against evidence contexts using the 4-type taxonomy.

    Enforces strict evidence abstention: tone, ambition, or absence of detail
    never triggers greenwashing.
    """
    if not claim_text or not claim_text.strip():
        return {
            "verdict": "abstain",
            "greenwashing_type": None,
            "justification": "Empty claim text.",
            "missing_evidence_reason": "No claim text provided.",
        }

    # Responsible abstention on empty context unless external LLM is provided
    if not contexts:
        if llm_fn is not None:
            prompt = format_qualitative_audit_prompt(claim_text, contexts=[])
            raw = llm_fn(prompt)
            return parse_audit_response(raw)

        return {
            "verdict": "abstain",
            "greenwashing_type": None,
            "justification": "Responsible abstention: No document context provided to verify or refute qualitative claim.",
            "missing_evidence_reason": "No document context provided.",
        }

    if llm_fn is not None:
        prompt = format_qualitative_audit_prompt(claim_text, contexts)
        raw = llm_fn(prompt)
        return parse_audit_response(raw)

    ctx_texts = []
    for c in contexts:
        if isinstance(c, dict):
            ctx_texts.append(c.get("content", str(c)))
        else:
            ctx_texts.append(str(c))
    full_ctx = "\n".join(ctx_texts).lower()
    c_lower = claim_text.lower()

    # 1. Type 1: False or unaccredited certifications/labels
    cert_matches = [m for m in ("iso 14001", "carbon neutral", "zero emissions", "net zero") if m in c_lower]
    if cert_matches:
        for m in cert_matches:
            if (
                "not certified" in full_ctx
                or "unaccredited" in full_ctx
                or "certification denied" in full_ctx
                or "certification is pending" in full_ctx
            ):
                return {
                    "verdict": "greenwashing",
                    "greenwashing_type": "Type 1",
                    "justification": f"Claim asserts '{m}' certification, but report context states certification is unaccredited or pending.",
                    "missing_evidence_reason": None,
                }

    # 2. Type 2: Legal/statutory obligations framed as voluntary
    mandate_keywords = ("euro 6", "euro vi", "bs-vi", "bs6", "statutory", "legally mandated", "mandatory compliance")
    voluntary_framings = ("voluntarily spearheaded", "pioneered voluntary", "our voluntary commitment")
    if any(m in c_lower or m in full_ctx for m in mandate_keywords):
        if any(v in c_lower for v in voluntary_framings):
            if "mandatory" in full_ctx or "statutory requirement" in full_ctx or "regulation" in full_ctx:
                return {
                    "verdict": "greenwashing",
                    "greenwashing_type": "Type 2",
                    "justification": "Action is legally mandated by regulation, but claim presents it as a voluntary initiative.",
                    "missing_evidence_reason": None,
                }

    # 3. Type 3: Boundary mismatch / partial truth presented as whole
    broad_claims = ("entire fleet", "all operations", "company-wide", "100% of vehicles")
    partial_evidence = ("limited to headquarters", "campus shuttles only", "pilot facility only", "excluding subsidiaries")
    if any(b in c_lower for b in broad_claims):
        for p in partial_evidence:
            if p in full_ctx:
                return {
                    "verdict": "greenwashing",
                    "greenwashing_type": "Type 3",
                    "justification": f"Claim asserts whole-boundary coverage, but context specifies scope is partial ('{p}').",
                    "missing_evidence_reason": None,
                }

    # 4. Type 4: Direct factual contradiction with evidence
    if "reduced emissions by" in c_lower:
        if "emissions increased" in full_ctx or "increase in scope 1" in full_ctx:
            return {
                "verdict": "greenwashing",
                "greenwashing_type": "Type 4",
                "justification": "Claim asserts emissions reduction, but context explicitly documents an increase in emissions.",
                "missing_evidence_reason": None,
            }

    # Direct verification check
    clean_claim = claim_text.strip().rstrip(".").lower()
    if clean_claim and clean_claim in full_ctx:
        return {
            "verdict": "verified",
            "greenwashing_type": None,
            "justification": "Claim text is explicitly corroborated by the report context.",
            "missing_evidence_reason": None,
        }

    # Default to responsible abstention when evidence is inconclusive
    return {
        "verdict": "abstain",
        "greenwashing_type": None,
        "justification": "Responsible abstention: Available context contains no verifiable facts to prove or refute claim.",
        "missing_evidence_reason": "Retrieved context does not contain conclusive evidence.",
    }


def scan_workspace_candidates(
    conn,
    root: Path,
    company: Optional[str] = None,
    claim_id: Optional[int] = None,
    llm_fn: Optional[Callable[[str], str]] = None,
) -> List[Dict[str, Any]]:
    """Scan claims in the workspace against page readings and propose greenwashing candidates for auditor review."""
    sql = """
    SELECT c.id AS claim_id, cv.id AS version_id, c.company_id, co.name AS company_name,
           c.document_id, d.logical_name AS document_name, er.page_number, cv.metric_text,
           er.boxes, a.path AS artifact_path
    FROM claim c
    JOIN claim_version cv ON cv.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)
    JOIN company co ON co.id = c.company_id
    JOIN document d ON d.id = c.document_id
    LEFT JOIN evidence_ref er ON er.claim_version_id = cv.id
    LEFT JOIN page p ON p.document_id = c.document_id AND p.page_number = er.page_number
    LEFT JOIN artifact a ON a.id = p.artifact_id
    WHERE 1=1
    """
    params = []
    if company:
        sql += " AND (co.name LIKE ? OR co.id = ?)"
        params.extend([f"%{company}%", company])
    if claim_id:
        sql += " AND c.id = ?"
        params.append(claim_id)

    sql += " ORDER BY c.id"
    rows = conn.execute(sql, params).fetchall()

    # Load claims that already have a reviewer flag recorded so we don't re-propose
    flagged_versions = {
        r[0] for r in conn.execute("SELECT claim_version_id FROM reviewer_flag").fetchall()
    }

    candidates = []
    for r in rows:
        cid, vid, co_id, co_name, doc_id, doc_name, page, text, boxes_json, art_path = r
        if vid in flagged_versions:
            continue

        contexts = []
        if art_path and (root / art_path).exists():
            try:
                reading = json.loads((root / art_path).read_text(encoding="utf-8"))
                words = reading.get("words", [])
                lines = " ".join(w.get("text", "") for w in words)
                contexts.append(lines)
            except Exception:
                pass

        audit_res = audit_claim(text, contexts, llm_fn=llm_fn)
        if audit_res["verdict"] == "greenwashing":
            boxes = json.loads(boxes_json) if boxes_json else None
            candidates.append({
                "claim_id": cid,
                "version_id": vid,
                "company": co_name,
                "document_id": doc_id,
                "document_name": doc_name,
                "page_number": page,
                "claim_text": text,
                "greenwashing_type": audit_res["greenwashing_type"],
                "justification": audit_res["justification"],
                "boxes": boxes,
                "evidence_quote": contexts[0][:200] if contexts else None,
                "status": "candidate_for_review",
            })

    return candidates
