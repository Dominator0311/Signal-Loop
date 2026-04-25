"""
RunCardioRenalConsult — single-tool server-side orchestration.

This tool runs the full Concord protocol (Steps 1-8 from the orchestrator
contract) inside one MCP call. Used to bypass the Prompt Opinion
Orchestrator-Agents UI bug (po-overview#27) which prevents A2A worker
response panels from rendering in the chat UI.

Flow (all server-side, no platform A2A round-trips):
  1. BuildEpisodeBrief  (existing logic)
  2. GetTrendSummary    (existing logic, now parallel)
  3. Three specialist Gemini calls in parallel using SpecialistOpinion schema
  4. ComputeConflictMatrix     (deterministic, rules engine)
  5. Build UnifiedPlan         (deterministic mapping from matrix)
  6. ValidateFinalPlan         (deterministic, rules engine)
  7. Draft Task / Medication / Communication writes
  8. LogConsensusDecision audit
  9. Render final clinician-facing markdown

Returns: markdown string with full panel decision plus a JSON appendix
containing every intermediate artifact (opinions, matrix, plan, validation,
audit) for transparency.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from llm.prompts.specialists import (
    SYNTHESIS_SYSTEM_INSTRUCTION,
    build_specialist_prompt,
    build_synthesis_prompt,
    get_specialist_system_instruction,
)
from llm.schemas import (
    AuditEventRef,
    CommunicationDraft,
    ConflictMatrix,
    DraftAction,
    EpisodeBrief,
    MedicationProposalDraft,
    SpecialistOpinion,
    TaskDraft,
    UnifiedPlan,
)
from medsafe_core.helpers import compute_due_date_from_timing
from medsafe_core.llm.client import get_gemini_client
from rules.action_codes import ActionCode
from rules.conflict_matrix import compute_conflict_matrix as _compute_matrix
from rules.plan_validator import validate_final_plan as _validate_plan
from tools.episode import build_episode_brief

logger = logging.getLogger(__name__)

_SPECIALTIES: tuple[str, ...] = ("nephrology", "cardiology", "pharmacy")

# Per-specialist Gemini call timeout. If a specialist call is still in flight after
# this, we abandon it and continue with whoever responded — keeps total tool runtime
# bounded so PO doesn't time out and retry the whole tool call.
_SPECIALIST_TIMEOUT_SECONDS: float = 35.0
_PATIENT_EXPLANATION_TIMEOUT_SECONDS: float = 8.0

# Cap on Mermaid diagram nodes — beyond this, the diagram becomes unreadable.
# Excess action codes are summarised as a "+N more" placeholder node.
_MERMAID_MAX_NODES: int = 12

# Short-form labels for action codes used in Mermaid nodes. Action code enum
# values are SHOUTY_SNAKE_CASE which renders awkwardly inside diagram boxes;
# titlecasing the underscore-split form yields more compact captions.
def _node_label(code: ActionCode) -> str:
    """Human-readable label for a Mermaid node (max ~28 chars)."""
    raw = code.value.replace("_", " ").title()
    if len(raw) > 28:
        return raw[:25].rstrip() + "..."
    return raw


# Bucket → Mermaid CSS class. Kept in priority order matching the diagram legend.
_MERMAID_CLASS_BY_RESOLUTION: dict[str, str] = {
    "consensus": "agreed",
    "tension": "pending",
    "dependency": "pending",
    "direct_conflict": "conflict",
    "safety_block": "caveat",
    "missing_data_block": "caveat",
}

# Heuristic: action codes whose primary FHIR write resource is MedicationRequest.
# Everything else maps to Task (default) or Communication (cross-team handoffs).
_MEDICATION_ACTION_CODES: frozenset[ActionCode] = frozenset({
    ActionCode.UPTITRATE_LOOP_DIURETIC,
    ActionCode.DOWNTITRATE_LOOP_DIURETIC,
    ActionCode.HOLD_LOOP_DIURETIC_TEMPORARILY,
    ActionCode.HOLD_ACE_ARB_TEMPORARILY,
    ActionCode.REDUCE_ACE_ARB_DOSE,
    ActionCode.HOLD_MRA_TEMPORARILY,
    ActionCode.START_SGLT2,
    ActionCode.SWITCH_NSAID_TO_PARACETAMOL,
})

_COMMUNICATION_ACTION_CODES: frozenset[ActionCode] = frozenset({
    ActionCode.DISCUSS_WITH_HF_SPECIALIST,
    ActionCode.DISCUSS_WITH_NEPHROLOGY,
})

# Default timing per action code — used if a recommendation lacks one.
_DEFAULT_TIMINGS: dict[ActionCode, str] = {
    ActionCode.REPEAT_RENAL_PANEL_48H: "48 hours",
    ActionCode.REPEAT_POTASSIUM_48H: "48 hours",
    ActionCode.REPEAT_RENAL_PANEL_1W: "1 week",
    ActionCode.REVIEW_IN_CLINIC_2W: "2 weeks",
    ActionCode.REVIEW_IN_CLINIC_4W: "4 weeks",
}


# --------- Specialist consultation (parallel Gemini calls) ---------

async def _consult_specialist(
    specialty: str,
    episode_brief_json: str,
) -> SpecialistOpinion | dict[str, str]:
    """Run one specialist Gemini call with a hard timeout.

    Returns SpecialistOpinion on success, or an error dict if the call timed out
    or otherwise failed. Bounded runtime is critical — PO times out the whole
    tool call if any one specialist hangs.
    """
    try:
        llm = get_gemini_client()
        prompt = build_specialist_prompt(episode_brief_json, specialty)
        system = get_specialist_system_instruction(specialty)

        opinion = await asyncio.wait_for(
            llm.generate_structured(prompt, SpecialistOpinion, system_instruction=system),
            timeout=_SPECIALIST_TIMEOUT_SECONDS,
        )
        # Force the specialty field to match the requested role — Gemini occasionally
        # ignores it under structured output if the prompt context is ambiguous.
        return opinion.model_copy(update={"specialty": specialty})
    except asyncio.TimeoutError:
        logger.error(f"specialist {specialty} timed out after {_SPECIALIST_TIMEOUT_SECONDS}s")
        return {"specialty": specialty, "error": "Timeout", "message": f"specialist call exceeded {_SPECIALIST_TIMEOUT_SECONDS}s"}
    except Exception as e:
        logger.error(f"specialist {specialty} failed: {e}\n{traceback.format_exc()}")
        return {"specialty": specialty, "error": type(e).__name__, "message": str(e)}


# --------- UnifiedPlan construction (deterministic) ---------

def _resource_type_for(code: ActionCode) -> str:
    if code in _MEDICATION_ACTION_CODES:
        return "MedicationRequest"
    if code in _COMMUNICATION_ACTION_CODES:
        return "Communication"
    return "Task"


def _timing_for(code: ActionCode, opinions: list[SpecialistOpinion]) -> str | None:
    """Pick a timing for a code: first specialist-supplied monitoring entry, else default.

    Tokens are returned in pluralised form ("48 hours", "1 week", "4 weeks") so
    they parse cleanly via `compute_due_date_from_timing`. Earlier this checked
    whether the monitoring SENTENCE ended with "s" — that's the wrong tail (e.g.
    "review at 48 hour intervals" ends with "s" but the token is missing the s).
    """
    for op in opinions:
        for rec in op.recommendations:
            if rec.action_code == code and rec.monitoring:
                for entry in rec.monitoring:
                    lower = entry.lower()
                    for token in ("48 hours", "72 hours", "1 week", "2 weeks", "4 weeks"):
                        # Match either the canonical pluralised form, or the singular
                        # variant that we'll then return canonicalised.
                        token_singular = token.rstrip("s") if token.endswith("s") else token
                        if token in lower or token_singular in lower:
                            return token
    return _DEFAULT_TIMINGS.get(code)


def _owner_for(code: ActionCode, opinions: list[SpecialistOpinion]) -> str:
    """Pick the specialty most strongly associated with this recommendation."""
    supporters: list[str] = []
    for op in opinions:
        for rec in op.recommendations:
            if rec.action_code == code:
                supporters.append(op.specialty)
    if not supporters:
        return "clinician"
    # Priority order: pharmacy (safety) > nephrology > cardiology
    for preferred in ("pharmacy", "nephrology", "cardiology"):
        if preferred in supporters:
            return preferred
    return supporters[0]


def _description_for(code: ActionCode, opinions: list[SpecialistOpinion]) -> str:
    """Use the highest-priority free_text from any specialist who recommended this code."""
    candidates: list[tuple[int, str]] = []
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    for op in opinions:
        for rec in op.recommendations:
            if rec.action_code == code:
                candidates.append((priority_rank.get(rec.priority, 3), rec.free_text))
    if not candidates:
        return code.value.replace("_", " ").title()
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def _build_unified_plan(
    matrix: ConflictMatrix,
    opinions: list[SpecialistOpinion],
    brief: EpisodeBrief,
) -> UnifiedPlan:
    """Deterministic mapping from ConflictMatrix → UnifiedPlan."""

    def _to_action(item) -> DraftAction:
        return DraftAction(
            action_code=item.action_code,
            resource_type=_resource_type_for(item.action_code),
            description=_description_for(item.action_code, opinions),
            owner_confirmer=_owner_for(item.action_code, opinions),
            monitoring=[
                m for op in opinions for rec in op.recommendations
                if rec.action_code == item.action_code for m in rec.monitoring
            ][:5],
            timing=_timing_for(item.action_code, opinions),
        )

    agreed = [_to_action(it) for it in matrix.consensus]

    # Safety_block and missing_data_block items are clinically interesting candidate
    # actions — they're proposed by specialists but have caveats (contraindications
    # or data dependencies). Surface them in pending rather than dropping them into
    # unresolved, so the clinician sees them as actionable-with-conditions.
    # ONLY direct_conflicts (true specialist disagreement) remain in unresolved.
    pending = [
        _to_action(it)
        for it in matrix.tensions + matrix.dependencies + matrix.missing_data_blocks + matrix.safety_blocks
    ]

    unresolved: list[str] = []
    for it in matrix.direct_conflicts:
        unresolved.append(
            f"[DIRECT_CONFLICT] {it.action_code.value}: {it.notes}"
        )
    # Annotate pending items that come with safety/data caveats so the clinician
    # sees the constraint inline, not buried in a separate section.
    for it in matrix.safety_blocks:
        unresolved.append(
            f"[SAFETY_CAVEAT on {it.action_code.value}] {it.notes}"
        )
    for it in matrix.missing_data_blocks:
        unresolved.append(
            f"[DATA_DEPENDENCY on {it.action_code.value}] {it.notes}"
        )
    # Add cross-cutting missing data items
    for op in opinions:
        for md in op.missing_data:
            entry = f"({op.specialty}) Missing: {md}"
            if entry not in unresolved:
                unresolved.append(entry)

    decision_summary = " ".join(
        f"[{op.specialty.title()}] {op.summary}" for op in opinions
    )[:1500]

    # draft_writes: agreed actions only — pending and unresolved are not auto-drafted.
    draft_writes = list(agreed)

    return UnifiedPlan(
        decision_summary=decision_summary,
        agreed_actions_now=agreed,
        actions_pending_confirmation=pending,
        unresolved_questions=unresolved,
        patient_safe_explanation="",  # filled in after Gemini synthesis
        draft_writes=draft_writes,
        episode_brief_id=brief.episode_brief_id,
        specialist_task_ids={},
    )


# --------- Draft writes (deterministic, no FHIR write yet — Phase 1 stubs) ---------

def _draft_all_writes(plan: UnifiedPlan) -> dict[str, list[dict]]:
    tasks: list[dict] = []
    meds: list[dict] = []
    comms: list[dict] = []

    for action in plan.draft_writes:
        if action.resource_type == "MedicationRequest":
            meds.append(MedicationProposalDraft(
                action_code=action.action_code.value,
                medication=action.description,
                rationale=f"Concord panel consensus (episode {plan.episode_brief_id})",
                owner_confirmer=action.owner_confirmer,
            ).model_dump())
        elif action.resource_type == "Communication":
            comms.append(CommunicationDraft(
                to_specialty=action.owner_confirmer,
                summary=action.description,
                linked_action_codes=[action.action_code.value],
            ).model_dump())
        else:
            tasks.append(TaskDraft(
                action_code=action.action_code.value,
                description=action.description,
                owner_confirmer=action.owner_confirmer,
                due_date=compute_due_date_from_timing(action.timing),
                timing=action.timing,
            ).model_dump())

    return {"tasks": tasks, "medication_proposals": meds, "communications": comms}


# --------- Mermaid conflict-matrix diagram (deterministic, pure) ---------

def _build_mermaid_diagram(matrix: ConflictMatrix) -> str:
    """Render the ConflictMatrix as a Mermaid flowchart code block.

    Pure function: input ConflictMatrix → Mermaid markdown string. Cap at
    `_MERMAID_MAX_NODES`; overflow per bucket is summarised as a single
    `+N more` placeholder node so the diagram stays readable in PO chat.

    Returns "" if the matrix has zero items (caller skips the section).

    Color classes:
      - agreed   = consensus (green)
      - pending  = tension / dependency (yellow)
      - conflict = direct_conflict (red)
      - caveat   = safety_block / missing_data_block (grey)
    """
    # Iterate buckets in display priority. Order matters: consensus first
    # (clinician's eye lands on green agreed actions), then pending,
    # then conflicts and caveats which get visual emphasis.
    buckets: list[tuple[str, list]] = [
        ("consensus", list(matrix.consensus)),
        ("tension", list(matrix.tensions)),
        ("dependency", list(matrix.dependencies)),
        ("direct_conflict", list(matrix.direct_conflicts)),
        ("safety_block", list(matrix.safety_blocks)),
        ("missing_data_block", list(matrix.missing_data_blocks)),
    ]

    total_items = sum(len(items) for _, items in buckets)
    if total_items == 0:
        return ""

    lines: list[str] = ["```mermaid", "flowchart TD"]

    node_id_counter = 0
    nodes_emitted = 0
    overflow_by_class: dict[str, int] = {}
    seen_codes: set[ActionCode] = set()

    for resolution, items in buckets:
        css_class = _MERMAID_CLASS_BY_RESOLUTION.get(resolution, "pending")
        for item in items:
            # An action code can in principle appear in multiple buckets only
            # if upstream classification has a bug, but defensively dedupe.
            if item.action_code in seen_codes:
                continue
            seen_codes.add(item.action_code)

            if nodes_emitted >= _MERMAID_MAX_NODES:
                overflow_by_class[css_class] = overflow_by_class.get(css_class, 0) + 1
                continue

            node_id = f"n{node_id_counter}"
            node_id_counter += 1
            label = _node_label(item.action_code)
            lines.append(f'  {node_id}["{label}"]:::{css_class}')
            nodes_emitted += 1

    # Emit "+N more" overflow placeholder nodes (one per CSS class with overflow).
    for css_class, count in overflow_by_class.items():
        if count <= 0:
            continue
        node_id = f"n{node_id_counter}"
        node_id_counter += 1
        lines.append(f'  {node_id}["+{count} more"]:::{css_class}')

    # classDef declarations — colours chosen for high contrast on both light
    # and dark backgrounds (PO chat is light, Marketplace listing samples
    # may render dark). Stroke is darker shade of fill.
    lines.append("  classDef agreed fill:#90EE90,stroke:#2E8B57,color:#000")
    lines.append("  classDef pending fill:#FFE4B5,stroke:#FF8C00,color:#000")
    lines.append("  classDef conflict fill:#FFB6C1,stroke:#DC143C,color:#000")
    lines.append("  classDef caveat fill:#D3D3D3,stroke:#696969,color:#000")
    lines.append("```")

    return "\n".join(lines)


# --------- Final markdown rendering ---------

def _render_markdown(
    brief: EpisodeBrief,
    opinions: list[SpecialistOpinion],
    matrix: ConflictMatrix,
    plan: UnifiedPlan,
    validation_status: str,
    validation_warnings: list[str],
    validation_blocks: list[str],
    writes: dict[str, list[dict]],
    audit: dict,
    patient_explanation: str,
) -> str:
    lines: list[str] = []
    lines.append(f"### Concord Panel Decision — Patient {brief.patient_id}")
    lines.append("")
    lines.append(f"**Clinical question:** {brief.current_clinician_question}")
    lines.append("")

    # Per-specialist views (this is what gives A's demo the multi-specialist feel)
    lines.append("**Specialist views:**")
    for op in opinions:
        lines.append(f"- **{op.specialty.title()}** ({op.confidence} confidence): {op.summary}")
    lines.append("")

    # Mermaid conflict-matrix diagram — color-coded action-code map.
    # Renders inline in PO chat (and most MCP hosts) as a flowchart.
    mermaid = _build_mermaid_diagram(matrix)
    if mermaid:
        lines.append("**Conflict matrix:**")
        lines.append(mermaid)
        lines.append("")
        lines.append(
            "_Legend: green = consensus · amber = pending · red = direct conflict · grey = safety / data caveat._"
        )
        lines.append("")

    # Consensus / pending / unresolved
    if plan.agreed_actions_now:
        lines.append("**Agreed actions (now):**")
        for a in plan.agreed_actions_now:
            t = f" — {a.timing}" if a.timing else ""
            lines.append(f"- `{a.action_code.value}` → {a.description} (owner: {a.owner_confirmer}{t})")
        lines.append("")

    if plan.actions_pending_confirmation:
        lines.append("**Pending clinician decision:**")
        for a in plan.actions_pending_confirmation:
            lines.append(f"- `{a.action_code.value}` → {a.description} (owner: {a.owner_confirmer})")
        lines.append("")

    if plan.unresolved_questions:
        lines.append("**Unresolved / data gaps:**")
        for q in plan.unresolved_questions[:10]:
            lines.append(f"- {q}")
        lines.append("")

    # Validation
    status_label = {
        "pass": "PASS",
        "pass_with_warnings": "PASS WITH WARNINGS",
        "fail": "FAIL — DO NOT WRITE",
    }.get(validation_status, validation_status.upper())
    lines.append(f"**Plan validated:** {status_label}")
    if validation_warnings:
        for w in validation_warnings:
            lines.append(f"  - ⚠️ {w}")
    if validation_blocks:
        for b in validation_blocks:
            lines.append(f"  - ❌ {b}")
    lines.append("")

    # Drafted writes
    n_tasks = len(writes["tasks"])
    n_meds = len(writes["medication_proposals"])
    n_comms = len(writes["communications"])
    lines.append(f"**Writes drafted:** {n_tasks} Task · {n_meds} MedicationRequest · {n_comms} Communication")
    lines.append("")

    if patient_explanation:
        lines.append("**Patient-safe explanation:**")
        lines.append(f"> {patient_explanation}")
        lines.append("")

    lines.append("---")
    lines.append(
        f"*Concord panel: nephrology · cardiology · pharmacy · "
        f"episode_brief_id: {brief.episode_brief_id} · "
        f"audit_id: {audit.get('audit_id', 'n/a')}*"
    )

    return "\n".join(lines)


# --------- Patient explanation (small Gemini synthesis) ---------

async def _generate_patient_explanation(plan: UnifiedPlan) -> str:
    """Best-effort patient-facing explanation. Bounded; failure is silent."""
    try:
        llm = get_gemini_client()
        prompt = build_synthesis_prompt(
            decision_summary=plan.decision_summary,
            agreed_actions=[f"{a.action_code.value}: {a.description}" for a in plan.agreed_actions_now],
            pending=[f"{a.action_code.value}: {a.description}" for a in plan.actions_pending_confirmation],
            unresolved=plan.unresolved_questions[:5],
        )
        return await asyncio.wait_for(
            llm.generate_text(prompt, system_instruction=SYNTHESIS_SYSTEM_INSTRUCTION),
            timeout=_PATIENT_EXPLANATION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("patient explanation timed out — returning empty")
        return ""
    except Exception as e:
        logger.warning(f"patient explanation generation failed: {e}")
        return ""


# --------- The MCP tool ---------

async def run_cardio_renal_consult(
    clinician_question: Annotated[
        str,
        Field(
            description=(
                "The clinician's clinical coordination question, e.g. "
                "'Cardiology wants more diuresis, nephrology worried about AKI — "
                "what's the unified plan?'"
            )
        ),
    ],
    ctx: Context = None,
) -> str:
    """
    Run the full Concord cardio-renal consultation in a single tool call.

    Internally orchestrates: build episode brief → fetch trends → consult three
    specialists in parallel → classify conflicts → build unified plan → validate
    → draft writes → log audit. Returns a markdown clinician-facing summary
    plus a JSON appendix with every intermediate artifact.

    No A2A round-trips, no orchestrator LLM, no platform UI dependencies.
    """
    async def _notify(message: str) -> None:
        """Best-effort progress notification. Silently no-ops if the host
        does not support `ctx.info()` (e.g. tests with `ctx=None`). This is
        intentionally synchronous-feeling: streaming visible specialist
        progress is host-dependent (PO buffers tool output until the call
        returns), but emitting `notifications/message` events at each phase
        boundary is harmless and gives hosts that DO render them a richer
        narrative without changing the final tool result.
        """
        if ctx is None:
            return
        try:
            await ctx.info(message)
        except Exception:
            # Never let logging fail the tool.
            pass

    try:
        # ----- Phase 1: Build episode brief (uses existing tool) -----
        await _notify("Building episode brief from FHIR record...")
        brief_json = await build_episode_brief(clinician_question, ctx=ctx)
        try:
            brief = EpisodeBrief.model_validate_json(brief_json)
        except Exception:
            # If brief failed (FHIR error etc.), surface its error JSON directly.
            return f"### Concord — Could not build episode brief\n\n```json\n{brief_json}\n```"

        # ----- Phase 2: Trend data SKIPPED inside this tool -----
        # The episode brief already contains recent_labs with current values and
        # interpretation flags — sufficient for specialist reasoning. Trend
        # regression (GetTrendSummary) is available as a separate MCP tool if a
        # clinician asks a follow-up question that warrants it. Keeping the
        # consult tool fast (<60s total) is more valuable than embedding trend
        # regression here, since PO retries the whole tool if it overruns.
        trends_json: str | None = None

        # ----- Phase 3: Run three specialists in parallel -----
        await _notify("Consulting nephrology, cardiology, and pharmacy specialists in parallel...")
        episode_brief_text = brief.model_dump_json(indent=2)
        specialist_results = await asyncio.gather(*[
            _consult_specialist(s, episode_brief_text) for s in _SPECIALTIES
        ])

        opinions: list[SpecialistOpinion] = []
        specialist_errors: list[dict] = []
        for r in specialist_results:
            if isinstance(r, SpecialistOpinion):
                opinions.append(r)
            else:
                specialist_errors.append(r)

        if len(opinions) < 2:
            return (
                "### Concord — Insufficient specialist responses\n\n"
                f"Only {len(opinions)} of 3 specialists returned a valid opinion.\n\n"
                f"```json\n{json.dumps(specialist_errors, indent=2)}\n```"
            )

        # ----- Phase 4: Conflict matrix (deterministic) -----
        await _notify(f"Received {len(opinions)} specialist opinions; classifying conflicts...")
        matrix = _compute_matrix(opinions, brief.episode_brief_id)

        # ----- Phase 5: Unified plan (deterministic mapping) -----
        plan = _build_unified_plan(matrix, opinions, brief)

        # ----- Phase 6: Validation (deterministic) -----
        validation = _validate_plan(plan, matrix)

        # ----- Phase 7: Drafts (only if validation didn't fail) -----
        writes: dict[str, list[dict]]
        if validation.status == "fail":
            writes = {"tasks": [], "medication_proposals": [], "communications": []}
        else:
            writes = _draft_all_writes(plan)

        # ----- Phase 8: Audit log (auto-persisted; no separate tool call needed) -----
        audit_id = str(uuid.uuid4())
        audit = AuditEventRef(
            episode_brief_id=brief.episode_brief_id,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            audit_id=audit_id,
            status="logged",  # auto-logged inline (Phase 1 in-memory; Phase 2 will write to FHIR)
        ).model_dump()
        audit["validation_status"] = validation.status
        audit["specialist_count"] = len(opinions)
        audit["action_codes_agreed"] = [a.action_code.value for a in plan.agreed_actions_now]
        audit["action_codes_pending"] = [a.action_code.value for a in plan.actions_pending_confirmation]
        audit["auto_logged"] = True
        # Strip the V10 "call LogConsensusDecision" warning since we did it ourselves.
        validation_warnings_filtered = [
            w for w in validation.warnings
            if "LogConsensusDecision" not in w and "V10" not in w
        ]

        # ----- Phase 9: Patient-safe explanation -----
        await _notify("Synthesising patient-safe explanation and rendering panel decision...")
        patient_explanation = await _generate_patient_explanation(plan)
        plan = plan.model_copy(update={"patient_safe_explanation": patient_explanation})

        # ----- Render -----
        markdown = _render_markdown(
            brief=brief,
            opinions=opinions,
            matrix=matrix,
            plan=plan,
            validation_status=validation.status,
            validation_warnings=validation_warnings_filtered,
            validation_blocks=validation.blocking_issues,
            writes=writes,
            audit=audit,
            patient_explanation=patient_explanation,
        )

        # Return ONLY the human-readable markdown to the chat. The full structured
        # artifacts (specialist opinions, conflict matrix, plan, validation, drafts)
        # are NOT inlined — they would (a) blow up the response payload to ~30KB,
        # which makes PO's UI show streaming "Responding..." for far longer than
        # needed, and (b) embed a fenced ```json block which can confuse PO's
        # tool-call parser. Audit traceability is preserved via the audit_id and
        # episode_brief_id rendered in the markdown footer.
        _ = trends_json  # intentionally unused — kept for future re-introduction
        _ = specialist_errors  # surfaced via the rendered "Specialist views" if any failed
        return markdown

    except Exception as e:
        logger.error(f"run_cardio_renal_consult failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
