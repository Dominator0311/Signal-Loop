"""
SHARP-on-MCP context extraction.

Extracts FHIR server URL, access token, and patient ID from the MCP request
context headers. These are injected by the Prompt Opinion platform on every
tool call when the MCP server has declared the ai.promptopinion/fhir-context
extension.

Header names (lowercase, as received by FastAPI/Starlette):
  - x-fhir-server-url: Base URL of the workspace FHIR server
  - x-fhir-access-token: Bearer token for FHIR server auth (optional)
  - x-patient-id: Active patient ID in patient-scope calls

Patient ID resolution order:
  1. 'patient' claim inside the JWT access token (if token is a JWT)
  2. x-patient-id header (fallback)
"""

from dataclasses import dataclass

import jwt
from mcp.server.fastmcp import Context


HEADER_FHIR_SERVER_URL = "x-fhir-server-url"
HEADER_FHIR_ACCESS_TOKEN = "x-fhir-access-token"
HEADER_PATIENT_ID = "x-patient-id"


@dataclass(frozen=True)
class FhirContext:
    """Immutable FHIR connection context extracted from SHARP headers."""

    server_url: str
    access_token: str | None = None
    patient_id: str | None = None


def extract_fhir_context(ctx: Context) -> FhirContext:
    """
    Extract FHIR context from MCP request headers.

    Raises ValueError if the required x-fhir-server-url header is missing.
    """
    request = ctx.request_context.request
    server_url = request.headers.get(HEADER_FHIR_SERVER_URL)

    if not server_url:
        raise ValueError(
            "FHIR context required but x-fhir-server-url header is missing. "
            "Ensure the MCP server is registered with FHIR context enabled in Prompt Opinion."
        )

    access_token = request.headers.get(HEADER_FHIR_ACCESS_TOKEN)
    patient_id = _resolve_patient_id(request.headers, access_token)

    return FhirContext(
        server_url=server_url.rstrip("/"),
        access_token=access_token,
        patient_id=patient_id,
    )


def extract_patient_id(ctx: Context) -> str:
    """
    Extract patient ID from MCP context. Raises ValueError if unavailable.

    Use this in tools that require patient scope.
    """
    fhir_ctx = extract_fhir_context(ctx)
    if not fhir_ctx.patient_id:
        raise ValueError(
            "Patient ID required but not found in FHIR context headers. "
            "Ensure the agent is running in patient scope."
        )
    return fhir_ctx.patient_id


def _resolve_patient_id(headers: dict, access_token: str | None) -> str | None:
    """
    Resolve patient ID from JWT claims or fallback to header.

    The platform may encode the patient ID in the JWT 'patient' claim
    of the access token, or pass it directly via x-patient-id header.
    """
    if access_token:
        try:
            claims = jwt.decode(
                access_token,
                options={"verify_signature": False},
            )
            patient_from_jwt = claims.get("patient")
            if patient_from_jwt:
                return str(patient_from_jwt)
        except (jwt.DecodeError, jwt.InvalidTokenError):
            pass

    return headers.get(HEADER_PATIENT_ID)
