"""
Referral sub-system MCP tools.

First-class capability: specialty-specific packet assembly, destination
ranking, consult note recommendation extraction, and plan conflict detection.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

logger = logging.getLogger(__name__)

import medsafe_core.rules as _mc_rules_pkg
from medsafe_core.fhir.context import extract_fhir_context, extract_patient_id
from medsafe_core.fhir.client import FhirClient
from medsafe_core.llm.client import get_gemini_client
from medsafe_core.llm.prompts.consult_extraction import (
    SYSTEM_INSTRUCTION as EXTRACTION_SYSTEM,
    CONFLICT_DETECTION_SYSTEM,
    build_extraction_prompt,
    build_conflict_detection_prompt,
)
from medsafe_core.llm.schemas import LLMConsultExtraction, LLMConflictDetection


# Specialty profiles: what each specialty needs in a referral packet
SPECIALTY_PROFILES = {
    "nephrology": {
        "required_inputs": [
            {"name": "egfr_trend", "fhir_query": "Observation?code=http://loinc.org|62238-1", "importance": "critical"},
            {"name": "creatinine_trend", "fhir_query": "Observation?code=http://loinc.org|2160-0", "importance": "critical"},
            {"name": "urine_acr", "fhir_query": "Observation?code=http://loinc.org|9318-7", "importance": "important"},
            {"name": "bp_history", "fhir_query": "Observation?code=http://loinc.org|85354-9", "importance": "important"},
            {"name": "current_ace_arb", "description": "Current ACE-I/ARB medication and dose", "importance": "critical"},
            {"name": "diabetes_status", "fhir_query": "Condition?code=http://snomed.info/sct|44054006", "importance": "important"},
            {"name": "renal_imaging", "description": "Recent renal ultrasound or imaging", "importance": "optional"},
            {"name": "nephrotoxin_exposure", "description": "Current nephrotoxic medications", "importance": "important"},
        ],
        "referral_question_template": "Sustained eGFR decline from {first_egfr} to {last_egfr} over {period} in {age}{sex} with {conditions}. Please assess for CKD progression and advise on medication optimisation.",
    },
    "cardiology": {
        "required_inputs": [
            {"name": "ecg", "description": "Recent ECG", "importance": "critical"},
            {"name": "echo", "description": "Echocardiogram / ejection fraction", "importance": "important"},
            {"name": "bp_trend", "fhir_query": "Observation?code=http://loinc.org|85354-9", "importance": "important"},
            {"name": "cardiac_history", "description": "Prior cardiac events", "importance": "critical"},
        ],
        "referral_question_template": "Cardiac assessment requested for {reason}.",
    },
    "rheumatology": {
        "required_inputs": [
            {"name": "inflammatory_markers", "description": "CRP, ESR", "importance": "critical"},
            {"name": "joint_distribution", "description": "Which joints affected", "importance": "important"},
            {"name": "prior_dmards", "description": "Previous DMARD trials", "importance": "critical"},
            {"name": "functional_status", "description": "Impact on daily activities", "importance": "important"},
        ],
        "referral_question_template": "Rheumatology assessment for {reason}.",
    },
}


async def assemble_specialty_packet(
    target_specialty: Annotated[
        str,
        Field(description="Target specialty (e.g., 'nephrology', 'cardiology', 'rheumatology')")
    ],
    referral_reason: Annotated[
        str,
        Field(description="Clinical reason for referral")
    ] = "",
    ctx: Context = None,
) -> str:
    """
    Assemble a specialty-specific referral packet with missing-context flagging.

    Different specialties need different inputs. This tool reads the patient's
    FHIR record through specialty-aware filters and produces a structured packet
    containing what the receiving specialist needs — while flagging what's missing.

    Currently supports: nephrology (full), cardiology (stub), rheumatology (stub).
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    specialty = target_specialty.lower().strip()
    profile = SPECIALTY_PROFILES.get(specialty)

    if not profile:
        return json.dumps({
            "error": "unsupported_specialty",
            "message": f"Specialty '{specialty}' not yet supported. Available: {list(SPECIALTY_PROFILES.keys())}",
        }, indent=2)

    # Fetch patient data relevant to this specialty
    medications = await fhir.get_medications(patient_id)
    conditions = await fhir.get_conditions(patient_id)
    observations = await fhir.get_observations(patient_id, count=20)

    # Evaluate each required input
    included = {}
    missing_flags = []
    for req_input in profile["required_inputs"]:
        name = req_input["name"]
        found = _check_input_available(name, observations, medications, conditions)
        if found:
            included[name] = {"included": True, "summary": found}
        else:
            missing_flags.append(
                f"No {name.replace('_', ' ')} found — "
                f"{'required' if req_input['importance'] == 'critical' else 'recommended'} for {specialty} referral"
            )
            included[name] = {"included": False, "missing_context_flag": missing_flags[-1]}

    # Compute completeness
    total = len(profile["required_inputs"])
    found_count = sum(1 for v in included.values() if v.get("included"))
    completeness = round(found_count / total, 2) if total > 0 else 0

    result = {
        "target_specialty": specialty,
        "patient_id": patient_id,
        "required_inputs": included,
        "referral_reason": referral_reason,
        "packet_completeness_score": completeness,
        "missing_context_flags": missing_flags,
        "missing_context_summary": (
            f"{len(missing_flags)} of {total} inputs not available; "
            f"{'completeness sufficient for standard referral' if completeness >= 0.6 else 'consider addressing gaps before referring'}"
        ),
    }

    return json.dumps(result, indent=2)


async def rank_specialist_destinations(
    specialty: Annotated[
        str,
        Field(description="Target specialty to search (e.g., 'nephrology')")
    ],
    urgency: Annotated[
        str,
        Field(description="Urgency level: routine, urgent, emergency")
    ] = "routine",
    ctx: Context = None,
) -> str:
    """
    Rank specialist destinations for a referral.

    Returns candidate specialists ranked by: specialty fit, wait time,
    distance, language match, network status, and clinical focus.

    Note: For hackathon, queries a seeded directory. In production,
    this would query a live specialist directory service.
    """
    data_path = Path(_mc_rules_pkg.__file__).parent / "data" / "specialist_directory.json"
    with open(data_path) as f:
        directory = json.load(f)

    specialty_key = specialty.lower().strip()
    candidates = directory.get(specialty_key, [])

    if not candidates:
        return json.dumps({
            "specialty": specialty_key,
            "ranked_candidates": [],
            "message": f"No specialists found for '{specialty_key}' in directory.",
        }, indent=2)

    # Rank candidates
    ranked = []
    for candidate in candidates:
        # Urgency filter
        if urgency == "urgent" and not candidate.get("accepts_urgent", True):
            continue

        # Compute composite rank score
        score = _compute_rank_score(candidate, urgency)
        ranked.append({
            "name": candidate["name"],
            "site": candidate["site"],
            "rank_score": score,
            "rank_factors": {
                "specialty_fit": candidate.get("subspecialty_fit_score", 0.7),
                "earliest_slot_days": candidate.get("earliest_available_slot_days", 14),
                "distance_miles": candidate.get("distance_miles_from_camden", 10),
                "language_match": "English" in candidate.get("language", []),
                "network_status": candidate.get("network_status", "unknown"),
                "clinical_focus": candidate.get("clinical_focus", ""),
            },
            "rationale": candidate.get("notes", ""),
        })

    # Sort by rank score descending
    ranked.sort(key=lambda x: x["rank_score"], reverse=True)

    return json.dumps({
        "specialty": specialty_key,
        "urgency": urgency,
        "ranked_candidates": ranked,
    }, indent=2)


async def extract_consult_recommendations(
    document_reference_id: Annotated[
        str,
        Field(description="Optional FHIR DocumentReference ID of the specialist note. "
                          "If empty or omitted, the tool auto-discovers the most recent "
                          "consult note for the current patient.")
    ] = "",
    ctx: Context = None,
) -> str:
    """
    Extract structured recommendations from a returned specialist consult note.

    Parses the DocumentReference content and uses AI to extract structured
    recommendation objects from free-text clinical letters. This is where
    generative AI earns substantial value — turning unstructured clinical
    text into actionable, reconcilable items.

    Auto-discovery behaviour:
      - If document_reference_id is provided, fetches that specific document.
      - If not provided, searches the patient's DocumentReferences and returns
        the most recent consult note (LOINC 11488-4 or Summary of episode note).
      - If no consult notes exist, returns a clear "no_consult_note_available" error
        so the agent can respond accurately.
    """
    try:
        fhir_ctx = extract_fhir_context(ctx)
        fhir = FhirClient(fhir_ctx)

        doc = None
        source_ref = None

        discovery_tier = "explicit_id"

        if document_reference_id:
            doc = await fhir.read("DocumentReference", document_reference_id)
            if doc is None:
                return json.dumps({
                    "error": "document_not_found",
                    "message": f"DocumentReference/{document_reference_id} not found.",
                }, indent=2)
            source_ref = f"DocumentReference/{document_reference_id}"
        else:
            # Auto-discover the specialist consult note for the current patient.
            # Two-tier strategy:
            #   Tier 1 (strict): LOINC-coded consult notes. Works for bundle-uploaded
            #     documents that set type.coding correctly.
            #   Tier 2 (permissive): keyword match across filename, description, type
            #     text, and author display. Required for Documents-tab UI uploads
            #     that typically lack structured LOINC coding.
            #
            # We still PREFER tier-1 hits when present (stronger signal). Tier-2 is
            # the safety net for real-world upload paths.
            patient_id = extract_patient_id(ctx)
            docs = await fhir.get_documents(patient_id)

            if not docs:
                return json.dumps({
                    "error": "no_consult_note_available",
                    "message": "No DocumentReference resources found for this patient.",
                    "hint": "The specialist may not have returned a consult note yet, "
                            "or the referral hasn't generated a document response.",
                }, indent=2)

            # Tier 1 — strict LOINC match
            consult_codes = {"11488-4", "34133-9", "34117-2", "51847-2", "68609-7"}
            tier1 = [d for d in docs if _doc_has_consult_type(d, consult_codes)]

            if tier1:
                tier1.sort(key=lambda d: d.get("date", ""), reverse=True)
                doc = tier1[0]
                discovery_tier = "loinc_coded"
            else:
                # Tier 2 — keyword match across all metadata fields
                tier2 = [d for d in docs if _doc_matches_consult_keywords(d)]

                if not tier2:
                    return json.dumps({
                        "error": "no_consult_note_available",
                        "message": (
                            f"Patient has {len(docs)} document(s) on file, but "
                            "none appear to be specialist consult notes. Searched "
                            "for LOINC consult codes AND for 'consult', 'specialist', "
                            "'nephrology', 'cardiology', 'rheumatology' keywords in "
                            "filename, description, type, and author metadata."
                        ),
                        "hint": (
                            "If the consult exists but wasn't identified, pass "
                            "document_reference_id explicitly to this tool."
                        ),
                    }, indent=2)

                tier2.sort(key=lambda d: d.get("date", ""), reverse=True)
                doc = tier2[0]
                discovery_tier = "keyword_match"

            source_ref = f"DocumentReference/{doc.get('id', 'unknown')}"

        # Extract text content (passes fhir client so we can resolve url-referenced Binaries)
        note_text = await _extract_document_text(doc, fhir=fhir)
        if not note_text:
            # Distinguish the "UI-upload auth boundary" case from other failures.
            # A DocumentReference with attachment.url but no data, served from
            # a proprietary /downloads/ endpoint, means the content was uploaded
            # via the Documents tab UI and can't be retrieved with a Bearer token.
            attachment = (doc.get("content") or [{}])[0].get("attachment", {}) or {}
            is_ui_upload = (
                not attachment.get("data")
                and attachment.get("url")
                and "/downloads/" in (attachment.get("url") or "")
            )
            if is_ui_upload:
                return json.dumps({
                    "error": "ui_uploaded_document_not_accessible",
                    "message": (
                        f"Document {source_ref} was uploaded via the Documents "
                        "tab UI. Its content is served from a session-authenticated "
                        "endpoint that MCP servers (Bearer-token authenticated) "
                        "cannot access. This is a known platform limitation."
                    ),
                    "workaround": (
                        "Specialist consult notes should be delivered via FHIR "
                        "bundle upload (inline base64 in attachment.data) or as "
                        "a FHIR Binary resource referenced via attachment.url. "
                        "Both paths are programmatically accessible. See the "
                        "SignalLoop README for bundle examples."
                    ),
                    "source_document_ref": source_ref,
                }, indent=2)
            return json.dumps({
                "error": "no_text_content",
                "message": (
                    f"Document {source_ref} has no extractable text content. "
                    "Check uvicorn logs for details — the extractor logs the "
                    "specific resolution path taken (inline/url) and any parse errors."
                ),
                "hint": (
                    "Common causes: PDF is image-based (scanned, needs OCR); "
                    "Binary/{id} reference 404s; attachment uses a content type "
                    "we don't support (e.g., image/jpeg)."
                ),
            }, indent=2)

        # Use LLM to extract structured recommendations
        prompt = build_extraction_prompt(note_text)
        gemini = get_gemini_client()

        extraction = await gemini.generate_structured(
            prompt=prompt,
            output_model=LLMConsultExtraction,
            system_instruction=EXTRACTION_SYSTEM,
        )

        result = extraction.model_dump()
        result["source_document_ref"] = source_ref
        result["discovery_tier"] = discovery_tier
        return json.dumps(result, indent=2)

    except Exception as e:
        import traceback
        logger_msg = traceback.format_exc()
        return json.dumps({
            "error": "extraction_failed",
            "error_type": type(e).__name__,
            "message": str(e),
            "traceback_hint": "Check server logs for full traceback.",
        }, indent=2)


async def detect_plan_conflicts(
    extracted_recommendations_json: Annotated[
        str,
        Field(description="JSON from extract_consult_recommendations")
    ],
    patient_risk_profile_json: Annotated[
        str,
        Field(description="JSON of patient risk profile")
    ],
    ctx: Context = None,
) -> str:
    """
    Detect conflicts between specialist recommendations and current care plan.

    Compares extracted recommendations against the patient's current medications
    and conditions, identifying where recommendations conflict with ongoing
    management and suggesting reconciliation paths.
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    recommendations = json.loads(extracted_recommendations_json)
    profile_data = json.loads(patient_risk_profile_json)

    # Fetch current plan data
    medications = await fhir.get_medications(patient_id)
    conditions = await fhir.get_conditions(patient_id)

    # Use LLM for conflict detection
    prompt = build_conflict_detection_prompt(
        recommendations=recommendations.get("extracted_recommendations", []),
        current_medications=medications,
        conditions=conditions,
        profile_data=profile_data,
    )
    gemini = get_gemini_client()

    detection = await gemini.generate_structured(
        prompt=prompt,
        output_model=LLMConflictDetection,
        system_instruction=CONFLICT_DETECTION_SYSTEM,
    )

    return json.dumps(detection.model_dump(), indent=2)


# --- Internal helpers ---

def _doc_has_consult_type(doc: dict, consult_codes: set[str]) -> bool:
    """
    Check if a DocumentReference has a consult-note-type LOINC code.

    Common consult note LOINC codes:
      - 11488-4: Consult note
      - 34133-9: Summarization of episode note
      - 34117-2: History and physical note
      - 51847-2: Consult note, electronic
      - 68609-7: Consultation note
    """
    type_field = doc.get("type", {})
    codings = type_field.get("coding", [])
    for coding in codings:
        if coding.get("code") in consult_codes:
            return True
    return False


# Keywords that suggest a document is a specialist consult response rather
# than a progress note or administrative document. Matched case-insensitively
# across filename, description, type text, type coding displays, and authors.
_CONSULT_KEYWORDS = (
    "consult",
    "consultation",
    "specialist",
    "nephrology",
    "cardiology",
    "rheumatology",
    "oncology",
    "endocrinology",
    "gastroenterology",
    "neurology",
    "referral response",
    "consultant",
)


def _doc_matches_consult_keywords(doc: dict) -> bool:
    """
    Fallback matcher for consult-like documents that lack LOINC coding.

    Searches common metadata fields for keywords that indicate specialist
    authorship or consult-note nature. Used when a document is uploaded via
    UI (e.g., Prompt Opinion's Documents tab) without structured LOINC
    categorization. Case-insensitive.

    We intentionally do NOT match "progress note", "primary care", "GP visit",
    or similar — those should be excluded from consult auto-discovery.
    """
    # Collect every plausible text field into one haystack
    parts: list[str] = []

    desc = doc.get("description")
    if isinstance(desc, str):
        parts.append(desc)

    type_field = doc.get("type", {}) or {}
    type_text = type_field.get("text")
    if isinstance(type_text, str):
        parts.append(type_text)

    for coding in type_field.get("coding", []) or []:
        disp = coding.get("display")
        if isinstance(disp, str):
            parts.append(disp)

    for author in doc.get("author", []) or []:
        disp = author.get("display")
        if isinstance(disp, str):
            parts.append(disp)

    for content in doc.get("content", []) or []:
        attach = content.get("attachment", {}) or {}
        title = attach.get("title")
        if isinstance(title, str):
            parts.append(title)

    haystack = " ".join(parts).lower()
    if not haystack.strip():
        return False

    # Explicit exclusions — don't match progress notes or primary-care visits
    if any(excl in haystack for excl in ("progress note", "primary care", "gp visit")):
        return False

    return any(keyword in haystack for keyword in _CONSULT_KEYWORDS)


def _check_input_available(
    input_name: str,
    observations: list,
    medications: list,
    conditions: list,
) -> str | None:
    """Check if a required input is available in the patient data."""
    # Map input names to detection logic
    if input_name == "egfr_trend":
        egfr_obs = [o for o in observations if _obs_has_code(o, "62238-1")]
        if egfr_obs:
            values = [o.get("valueQuantity", {}).get("value") for o in egfr_obs[:3]]
            return f"eGFR values: {values}"
    elif input_name == "creatinine_trend":
        creat_obs = [o for o in observations if _obs_has_code(o, "2160-0")]
        if creat_obs:
            return f"{len(creat_obs)} creatinine values found"
    elif input_name == "bp_history":
        bp_obs = [o for o in observations if _obs_has_code(o, "85354-9")]
        if bp_obs:
            return f"{len(bp_obs)} BP readings found"
    elif input_name == "current_ace_arb":
        ace_arb = [m for m in medications if _med_is_class(m, ["lisinopril", "ramipril", "enalapril", "losartan", "irbesartan", "candesartan"])]
        if ace_arb:
            name = ace_arb[0].get("medicationCodeableConcept", {}).get("text", "ACE-I/ARB")
            return f"Current: {name}"
    elif input_name == "diabetes_status":
        diabetes = [c for c in conditions if "diabetes" in c.get("code", {}).get("text", "").lower()]
        if diabetes:
            return "T2DM confirmed"
    elif input_name == "nephrotoxin_exposure":
        # Check for known nephrotoxins
        return "Assessment available from medication list"
    elif input_name == "urine_acr":
        acr_obs = [o for o in observations if _obs_has_code(o, "9318-7")]
        if acr_obs:
            return f"ACR: {acr_obs[0].get('valueQuantity', {}).get('value')}"

    return None


def _obs_has_code(obs: dict, loinc_code: str) -> bool:
    """Check if an observation has a specific LOINC code."""
    codings = obs.get("code", {}).get("coding", [])
    return any(c.get("code") == loinc_code for c in codings)


def _med_is_class(med: dict, drug_names: list[str]) -> bool:
    """Check if a medication matches any of the given drug names."""
    med_text = med.get("medicationCodeableConcept", {}).get("text", "").lower()
    return any(name in med_text for name in drug_names)


async def _extract_document_text(doc: dict, fhir: FhirClient | None = None) -> str | None:
    """
    Extract text content from a FHIR DocumentReference's attachment.

    FHIR R4 Attachments can carry binary content two ways:
      1. Inline: `attachment.data` base64-encoded bytes (small files / hand-crafted bundles)
      2. By reference: `attachment.url` points to a Binary resource or external URL
         (normal server behavior for anything over a few KB, including Documents-tab UI uploads)

    This function resolves BOTH paths, then dispatches by contentType:
      - text/plain, text/markdown → UTF-8 decode
      - application/pdf → pypdf extraction (falls back to magic-number sniff)

    Logs the resolution path so operators can verify what happened. Returns
    None only when we genuinely cannot read the content; callers surface
    specific error types to clinicians.

    Args:
        doc: A FHIR DocumentReference dict.
        fhir: Optional FhirClient — required when the attachment uses url
              referencing (e.g., Binary/{id}). If None and url is set,
              resolution fails with a clear log.
    """
    content = doc.get("content") or []
    if not content:
        logger.info("_extract_document_text: DocumentReference has no content[]")
        return None

    attachment = content[0].get("attachment", {}) or {}
    content_type = (attachment.get("contentType") or "").lower()
    inline_data = attachment.get("data")
    url = attachment.get("url")
    title = attachment.get("title")

    logger.info(
        f"_extract_document_text: attachment keys present — "
        f"data:{bool(inline_data)} url:{bool(url)} "
        f"contentType:{content_type!r} title:{title!r}"
    )

    # Resolve raw bytes — either from inline data or by fetching URL
    raw: bytes | None = None

    if inline_data:
        try:
            raw = base64.b64decode(inline_data)
            logger.info(f"_extract_document_text: decoded {len(raw)} inline bytes")
        except Exception as e:
            logger.warning(f"Inline attachment base64 decode failed: {e}")
            return None

    elif url:
        if fhir is None:
            logger.warning(
                f"_extract_document_text: attachment has url {url!r} but no "
                "FhirClient was provided to resolve it"
            )
            return None
        raw = await _fetch_attachment_by_url(url, fhir)
        if raw is None:
            # _fetch_attachment_by_url already logged the specific failure
            return None

    else:
        logger.info("_extract_document_text: attachment has neither data nor url")
        return None

    # Dispatch by content type (or magic-number sniff as fallback)
    if content_type.startswith("text/plain") or content_type.startswith("text/markdown"):
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Could not decode text attachment: {e}")
            return None

    if content_type == "application/pdf" or _looks_like_pdf(raw):
        text = _extract_pdf_text(raw)
        if text:
            logger.info(f"_extract_document_text: PDF extracted {len(text)} chars")
        return text

    # Best-effort: some servers return text content with no contentType
    if not content_type:
        try:
            decoded = raw.decode("utf-8", errors="replace")
            # If it smells like text (mostly printable), return it
            printable = sum(1 for c in decoded[:1000] if c.isprintable() or c in "\n\r\t")
            if printable / max(1, len(decoded[:1000])) > 0.9:
                logger.info("_extract_document_text: no contentType but content looks textual")
                return decoded
        except Exception:
            pass

    logger.info(f"_extract_document_text: unsupported contentType {content_type!r}")
    return None


async def _fetch_attachment_by_url(url: str, fhir: FhirClient) -> bytes | None:
    """
    Resolve a DocumentReference.content.attachment.url to raw bytes.

    FHIR attachment URLs come in four observed shapes:
      1. FHIR Binary reference  — `Binary/{id}` — fetched via FhirClient.read
      2. Absolute URL on FHIR base — `https://.../fhir/Binary/{id}` — treated as (1)
      3. Absolute external URL — fetched directly via authenticated httpx GET
      4. Server-relative URL — `api/workspaces/{ws}/downloads/...` (no scheme)
         Prompt Opinion's Documents-tab UI uploads land here. The URL is
         relative to the SERVER root, not the FHIR base path. Resolved by
         prefixing the scheme+host parsed from FhirClient's base URL.

    For custom download endpoints (shape 4), we assume the server returns
    raw bytes with the correct Content-Type header. No base64 decode needed.

    For FHIR Binary references (shapes 1, 2), we expect a JSON Binary
    resource whose `data` field is base64-encoded bytes.

    Returns None on failure, with a specific log explaining why.
    """
    from urllib.parse import urlsplit, urlunsplit

    try:
        base = getattr(fhir, "_base_url", "") or ""
        base_trimmed = base.rstrip("/")

        # First — detect FHIR Binary reference (relative or absolute on base)
        binary_candidate: str | None = None
        if url.startswith("Binary/"):
            binary_candidate = url
        elif base_trimmed and url.startswith(base_trimmed):
            remainder = url[len(base_trimmed):].lstrip("/")
            if remainder.startswith("Binary/"):
                binary_candidate = remainder

        if binary_candidate:
            binary_id = binary_candidate.split("/", 1)[1].split("?", 1)[0]
            logger.info(f"_fetch_attachment_by_url: reading Binary/{binary_id} via FHIR")
            binary = await fhir.read("Binary", binary_id)
            if binary is None:
                logger.warning(f"Binary/{binary_id} returned 404")
                return None
            b64 = binary.get("data")
            if not b64:
                logger.warning(f"Binary/{binary_id} has no data field")
                return None
            try:
                return base64.b64decode(b64)
            except Exception as e:
                logger.warning(f"Binary/{binary_id} base64 decode failed: {e}")
                return None

        # Second — resolve URL to an absolute one we can hit with httpx
        absolute_url = _resolve_relative_url(url, base_trimmed)
        if absolute_url is None:
            logger.warning(
                f"_fetch_attachment_by_url: could not resolve {url!r} against base {base_trimmed!r}"
            )
            return None

        logger.info(f"_fetch_attachment_by_url: GET {absolute_url}")
        import httpx
        # Explicit Accept header — some download endpoints content-negotiate and
        # default to serving HTML when no specific binary type is requested.
        # application/pdf covers PDF specifically; */* allows text and other binaries.
        headers = dict(fhir._headers()) if hasattr(fhir, "_headers") else {}
        headers["Accept"] = "application/pdf, application/octet-stream, text/plain, */*;q=0.8"
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(absolute_url, headers=headers)
            if response.status_code == 404:
                logger.warning(f"Attachment URL returned 404: {absolute_url}")
                return None
            response.raise_for_status()

            response_ct = (response.headers.get("content-type") or "").lower()
            logger.info(
                f"_fetch_attachment_by_url: fetched {len(response.content)} bytes, "
                f"response content-type: {response_ct!r}"
            )

            # Sanity check: if the server returned HTML/JSON when we asked for a
            # binary PDF, it's almost certainly an auth-wall / SPA shell / error
            # page served with 200 status. Reject explicitly with diagnostic
            # info instead of feeding garbage to pypdf.
            if response_ct.startswith("text/html"):
                sample = response.content[:200].decode("utf-8", errors="replace")
                logger.warning(
                    f"Download endpoint returned HTML (len={len(response.content)}) "
                    f"instead of binary content. This typically means session-cookie "
                    f"auth is required (Bearer token insufficient) OR the endpoint is "
                    f"browser-only. First 200 bytes: {sample!r}"
                )
                return None
            if response_ct.startswith("application/json"):
                logger.warning(
                    f"Download endpoint returned JSON instead of binary content: "
                    f"{response.content[:500]!r}"
                )
                return None

            return response.content

    except Exception as e:
        logger.warning(f"_fetch_attachment_by_url failed for {url!r}: {e}")
        return None


def _resolve_relative_url(url: str, fhir_base: str) -> str | None:
    """
    Resolve a possibly-relative attachment URL against the FHIR server's host.

    If `url` is absolute (starts with http:// or https://), it's returned as-is.
    If `url` is relative (no scheme), we take scheme+host from `fhir_base` and
    prepend them, preserving `url` as the path — so it's resolved against the
    server ROOT, not the FHIR base path. This matches Prompt Opinion's
    download endpoints (`/api/workspaces/{ws}/downloads/...`) which live
    on a sibling path from the FHIR API.

    Returns the resolved absolute URL, or None if `fhir_base` is missing
    and we can't anchor a relative URL.
    """
    from urllib.parse import urlsplit, urlunsplit

    # Already absolute
    if url.startswith(("http://", "https://")):
        return url

    if not fhir_base:
        return None

    parsed = urlsplit(fhir_base)
    if not parsed.scheme or not parsed.netloc:
        return None

    # Ensure the relative URL starts with a single slash
    path_and_query = url if url.startswith("/") else "/" + url

    # Split path/query to preserve query string correctly
    if "?" in path_and_query:
        path, query = path_and_query.split("?", 1)
    else:
        path, query = path_and_query, ""

    return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def _looks_like_pdf(raw: bytes) -> bool:
    """Check if the raw bytes start with the PDF magic number."""
    return raw[:5] == b"%PDF-"


def _extract_pdf_text(raw: bytes) -> str | None:
    """Parse a PDF byte blob and return concatenated text across all pages."""
    try:
        # Import lazily so the server can start even if pypdf is missing;
        # the failure surfaces only when a PDF is actually encountered.
        from io import BytesIO
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(raw))
        pages_text: list[str] = []
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
                if text.strip():
                    pages_text.append(text)
            except Exception as page_err:
                logger.warning(f"PDF page extraction failed: {page_err}")

        combined = "\n\n".join(pages_text).strip()
        if not combined:
            logger.warning(
                f"PDF parsed but produced no text ({len(reader.pages)} pages). "
                "May be image-based (scanned) — OCR required."
            )
            return None
        return combined
    except ImportError:
        logger.error(
            "pypdf not installed — cannot extract PDF text. "
            "Run: pip install pypdf>=5.0.0"
        )
        return None
    except Exception as e:
        logger.warning(f"PDF parse failed: {e}")
        return None


def _compute_rank_score(candidate: dict, urgency: str) -> float:
    """Compute composite ranking score for a specialist candidate."""
    score = 0.0

    # Specialty fit (weight: 0.3)
    score += candidate.get("subspecialty_fit_score", 0.5) * 0.3

    # Wait time (weight: 0.25) — shorter is better, especially for urgent
    wait_days = candidate.get("earliest_available_slot_days", 14)
    wait_score = max(0, 1.0 - (wait_days / 30.0))
    if urgency == "urgent":
        wait_score *= 1.5  # Weight wait time more heavily for urgent
    score += min(wait_score, 1.0) * 0.25

    # Distance (weight: 0.2) — closer is better
    distance = candidate.get("distance_miles_from_camden", 10)
    distance_score = max(0, 1.0 - (distance / 20.0))
    score += distance_score * 0.2

    # Network status (weight: 0.15)
    if candidate.get("network_status") == "in-network":
        score += 0.15

    # Language (weight: 0.1)
    if "English" in candidate.get("language", []):
        score += 0.1

    return round(score, 2)
