"""
Async FHIR R4 HTTP client.

Provides read and write operations against a FHIR server using the
connection details from SHARP context headers. All operations are
async and use httpx for HTTP transport.

Design principles:
  - Immutable after construction (connection params set once)
  - All methods return typed results or None for 404
  - Write operations return the created/updated resource with server-assigned ID
  - Errors raise exceptions with clear messages (callers handle)
"""

from typing import Any

import httpx

from medsafe_core.fhir.context import FhirContext


class FhirClient:
    """Async FHIR R4 client for workspace FHIR server operations."""

    def __init__(self, context: FhirContext) -> None:
        self._base_url = context.server_url
        self._token = context.access_token

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/fhir+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"

    async def read(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        """
        Read a single FHIR resource by type and ID.

        Returns the resource dict or None if not found (404).
        Raises httpx.HTTPStatusError for other HTTP errors.
        """
        url = self._url(f"{resource_type}/{resource_id}")
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            response = await client.get(url, headers=self._headers())
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    async def search(
        self,
        resource_type: str,
        params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for FHIR resources. Returns list of matching resources.

        Handles Bundle response format — extracts resources from entries.
        Returns empty list if no matches.
        """
        url = self._url(resource_type)
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            bundle = response.json()

        entries = bundle.get("entry", [])
        return [entry["resource"] for entry in entries if "resource" in entry]

    async def create(self, resource_type: str, resource: dict[str, Any]) -> dict[str, Any]:
        """
        Create a new FHIR resource (POST). Returns the created resource
        with server-assigned ID.
        """
        url = self._url(resource_type)
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            response = await client.post(url, headers=self._headers(), json=resource)
            response.raise_for_status()
            return response.json()

    async def update(self, resource_type: str, resource_id: str, resource: dict[str, Any]) -> dict[str, Any]:
        """
        Update an existing FHIR resource (PUT). Returns the updated resource.
        """
        url = self._url(f"{resource_type}/{resource_id}")
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            response = await client.put(url, headers=self._headers(), json=resource)
            response.raise_for_status()
            return response.json()

    async def get_patient(self, patient_id: str) -> dict[str, Any] | None:
        """Convenience: read a Patient resource."""
        return await self.read("Patient", patient_id)

    async def get_conditions(self, patient_id: str) -> list[dict[str, Any]]:
        """Get all active conditions for a patient."""
        return await self.search("Condition", {"patient": patient_id, "clinical-status": "active"})

    async def get_medications(self, patient_id: str) -> list[dict[str, Any]]:
        """Get all active medication requests for a patient."""
        return await self.search("MedicationRequest", {"patient": patient_id, "status": "active"})

    async def get_allergies(self, patient_id: str) -> list[dict[str, Any]]:
        """Get all allergy intolerances for a patient."""
        return await self.search("AllergyIntolerance", {"patient": patient_id})

    async def get_observations(
        self,
        patient_id: str,
        code: str | None = None,
        sort: str = "-date",
        count: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Get observations for a patient, optionally filtered by LOINC code.

        Args:
            patient_id: FHIR patient ID
            code: LOINC code to filter by (e.g., "62238-1" for eGFR)
            sort: Sort order (default: newest first)
            count: Max results to return
        """
        params: dict[str, str] = {
            "patient": patient_id,
            "_sort": sort,
            "_count": str(count),
        }
        if code:
            params["code"] = f"http://loinc.org|{code}"
        return await self.search("Observation", params)

    async def get_documents(self, patient_id: str) -> list[dict[str, Any]]:
        """Get all document references for a patient."""
        return await self.search("DocumentReference", {"patient": patient_id})
