"""
FHIR integration layer.

Handles SHARP header extraction from MCP context and all HTTP communication
with the workspace FHIR server (reads and writes).
"""

from fhir.client import FhirClient
from fhir.context import extract_fhir_context, extract_patient_id, FhirContext

__all__ = ["FhirClient", "FhirContext", "extract_fhir_context", "extract_patient_id"]
