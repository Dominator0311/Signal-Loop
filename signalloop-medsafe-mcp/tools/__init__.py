"""
MCP tool implementations.

Each module corresponds to a phase of the MedSafe architecture:
  - phase1.py: Patient risk profile building (LLM-driven)
  - phase2.py: Deterministic medication safety check (rules engine)
  - phase3.py: Response synthesis and override analysis (LLM-driven)
  - referral.py: Specialty-specific referral sub-system
  - writes.py: FHIR resource creation (writes)
"""
