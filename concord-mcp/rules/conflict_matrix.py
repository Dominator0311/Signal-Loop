"""
ComputeConflictMatrix — pure Python, no LLM.

Groups recommendations by action_code across all specialist opinions,
then classifies each group using the resolution taxonomy (priority order):
  safety_block > direct_conflict > missing_data_block > dependency > consensus/tension

The MCP tool wrapper lives in tools/arbitration.py.
"""

from collections import defaultdict

from llm.schemas import ConflictItem, ConflictMatrix, SpecialistOpinion
from rules.action_codes import ActionCode, OPPOSING_PAIRS, SAFETY_PRIORITY_CODES


def _build_opposing_map() -> dict[ActionCode, frozenset[ActionCode]]:
    """Build a bidirectional map: code → frozenset of all codes that oppose it."""
    result: dict[ActionCode, set[ActionCode]] = defaultdict(set)
    for a, b in OPPOSING_PAIRS:
        result[a].add(b)
        result[b].add(a)
    return {k: frozenset(v) for k, v in result.items()}


_OPPOSING_MAP: dict[ActionCode, frozenset[ActionCode]] = _build_opposing_map()


def compute_conflict_matrix(
    opinions: list[SpecialistOpinion],
    episode_brief_id: str,
) -> ConflictMatrix:
    """
    Classify specialist opinions into the ConflictMatrix taxonomy.

    Classification priority for each action_code:
      1. safety_block  — code in SAFETY_PRIORITY_CODES or any rec has contraindications
      2. direct_conflict — an opposing code is also recommended by a different specialty
      3. missing_data_block — rec has dependencies AND supporting specialty has missing_data
      4. dependency  — rec has non-empty dependencies
      5. consensus   — 2+ specialties support, no opposing code recommended
      6. tension     — 1 specialty supports, no opposing code recommended
    """
    # Index recs by action_code: code → list of (specialty, recommendation)
    code_to_recs: dict[ActionCode, list[tuple[str, object]]] = defaultdict(list)
    for opinion in opinions:
        for rec in opinion.recommendations:
            code_to_recs[rec.action_code].append((opinion.specialty, rec))

    if not code_to_recs:
        return ConflictMatrix(
            consensus=[],
            tensions=[],
            direct_conflicts=[],
            dependencies=[],
            missing_data_blocks=[],
            safety_blocks=[],
            ranked_next_actions=[],
            episode_brief_id=episode_brief_id,
        )

    specialty_to_opinion: dict[str, SpecialistOpinion] = {o.specialty: o for o in opinions}
    all_recommended: frozenset[ActionCode] = frozenset(code_to_recs.keys())

    consensus: list[ConflictItem] = []
    tensions: list[ConflictItem] = []
    direct_conflicts: list[ConflictItem] = []
    dependencies: list[ConflictItem] = []
    missing_data_blocks: list[ConflictItem] = []
    safety_blocks: list[ConflictItem] = []

    for code, rec_list in code_to_recs.items():
        # Preserve first-occurrence order of specialties
        supporting: list[str] = list(dict.fromkeys(s for s, _ in rec_list))
        recs = [r for _, r in rec_list]

        has_deps = any(bool(r.dependencies) for r in recs)
        has_contraindications = any(bool(r.contraindications) for r in recs)
        any_missing_data = any(
            bool(specialty_to_opinion[s].missing_data)
            for s in supporting
            if s in specialty_to_opinion
        )

        # Opposing codes that are actually recommended by some specialty
        active_opposing: frozenset[ActionCode] = _OPPOSING_MAP.get(code, frozenset()) & all_recommended

        # Specialties that support an opposing code (excluding those who also support this code)
        opposing: list[str] = list(dict.fromkeys(
            s
            for opp_code in active_opposing
            for s, _ in code_to_recs.get(opp_code, [])
            if s not in supporting
        ))

        # --- Priority classification ---
        if code in SAFETY_PRIORITY_CODES or has_contraindications:
            notes = f"Safety-critical action: {code.value}."
            if has_contraindications:
                notes += " Contraindications noted by a specialist."
            safety_blocks.append(ConflictItem(
                action_code=code,
                specialties_supporting=supporting,
                specialties_opposing=opposing,
                resolution="safety_block",
                severity="high",
                notes=notes,
            ))

        elif active_opposing and opposing:
            direct_conflicts.append(ConflictItem(
                action_code=code,
                specialties_supporting=supporting,
                specialties_opposing=opposing,
                resolution="direct_conflict",
                severity="high",
                notes=f"Directly opposed by: {', '.join(c.value for c in active_opposing)}.",
            ))

        elif has_deps and any_missing_data:
            missing_data_blocks.append(ConflictItem(
                action_code=code,
                specialties_supporting=supporting,
                specialties_opposing=[],
                resolution="missing_data_block",
                severity="medium",
                notes="Action has dependencies but supporting specialty reports missing clinical data.",
            ))

        elif has_deps:
            dependencies.append(ConflictItem(
                action_code=code,
                specialties_supporting=supporting,
                specialties_opposing=[],
                resolution="dependency",
                severity="low",
                notes="Action has dependencies on other actions.",
            ))

        elif len(supporting) >= 2:
            consensus.append(ConflictItem(
                action_code=code,
                specialties_supporting=supporting,
                specialties_opposing=[],
                resolution="consensus",
                severity="low",
                notes=f"Agreed by {len(supporting)} specialties.",
            ))

        else:
            tensions.append(ConflictItem(
                action_code=code,
                specialties_supporting=supporting,
                specialties_opposing=[],
                resolution="tension",
                severity="low",
                notes=f"Single specialty recommendation from {supporting[0] if supporting else 'unknown'}.",
            ))

    # Ranked next actions: safety_blocks → consensus → tensions → dependencies
    #                        → missing_data_blocks → direct_conflicts
    seen: set[ActionCode] = set()
    ranked: list[ActionCode] = []
    for bucket in [safety_blocks, consensus, tensions, dependencies, missing_data_blocks, direct_conflicts]:
        for item in bucket:
            if item.action_code not in seen:
                seen.add(item.action_code)
                ranked.append(item.action_code)

    return ConflictMatrix(
        consensus=consensus,
        tensions=tensions,
        direct_conflicts=direct_conflicts,
        dependencies=dependencies,
        missing_data_blocks=missing_data_blocks,
        safety_blocks=safety_blocks,
        ranked_next_actions=ranked,
        episode_brief_id=episode_brief_id,
    )
