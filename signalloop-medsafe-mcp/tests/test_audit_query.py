"""Tests for QueryAuditEvent — read-only counterpart to LogOverride."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from tools.audit_query import _summarise_audit_event, query_audit_event


# --- Pure summariser ---


def test_summarise_audit_event_basic():
    raw = {
        "id": "ae-1",
        "recorded": "2026-04-10T09:00:00Z",
        "action": "E",
        "agent": [{"name": "Dr Patel"}],
        "outcome": "0",
        "extension": [
            {"url": "http://example.org/audit-description",
             "valueString": "MedSafe override: naproxen at eGFR 41."},
        ],
    }
    summary = _summarise_audit_event(raw)
    assert summary["id"] == "ae-1"
    assert summary["recorded_at"] == "2026-04-10T09:00:00Z"
    assert summary["action"] == "E"
    assert "Dr Patel" in summary["agents"]
    assert "naproxen" in summary["description"]


def test_summarise_audit_event_falls_back_when_no_extension():
    raw = {
        "id": "ae-2",
        "recorded": "2026-04-12T10:00:00Z",
        "outcomeDesc": "fallback description",
        "agent": [],
    }
    summary = _summarise_audit_event(raw)
    assert summary["description"] == "fallback description"
    assert summary["agents"] == []


# --- End-to-end tool with mocked FHIR client ---


def test_query_audit_event_returns_summarised_list():
    fake_events = [
        {
            "id": "ae-A",
            "recorded": "2026-04-15T10:00:00Z",
            "action": "E",
            "agent": [{"name": "Dr Patel"}],
            "extension": [{"url": "x:audit-description",
                           "valueString": "Override: naproxen eGFR 41"}],
        },
        {
            "id": "ae-B",
            "recorded": "2026-04-01T08:00:00Z",
            "action": "E",
            "agent": [{"name": "Dr Webb"}],
            "extension": [{"url": "x:audit-description",
                           "valueString": "Override: ibuprofen eGFR 38"}],
        },
    ]

    async def fake_search(rt, params):
        assert rt == "AuditEvent"
        assert params["patient"] == "p-margaret"
        return fake_events

    with (
        patch("tools.audit_query.FhirClient") as MockClient,
        patch("tools.audit_query.extract_patient_id", return_value="p-margaret"),
        patch("tools.audit_query.extract_fhir_context") as mock_ctx,
    ):
        instance = MockClient.return_value
        instance.search = AsyncMock(side_effect=fake_search)
        result_json = asyncio.run(query_audit_event(since="", drug_filter="", limit=10, ctx=None))

    result = json.loads(result_json)
    assert result["count"] == 2
    assert result["events"][0]["id"] == "ae-A"
    assert "naproxen" in result["events"][0]["description"]


def test_query_audit_event_filters_by_drug():
    fake_events = [
        {"id": "1", "recorded": "2026-04-15", "action": "E", "agent": [],
         "extension": [{"url": "x:audit-description", "valueString": "Override: naproxen"}]},
        {"id": "2", "recorded": "2026-04-12", "action": "E", "agent": [],
         "extension": [{"url": "x:audit-description", "valueString": "Override: ibuprofen"}]},
    ]

    async def fake_search(rt, params):
        return fake_events

    with (
        patch("tools.audit_query.FhirClient") as MockClient,
        patch("tools.audit_query.extract_patient_id", return_value="p"),
        patch("tools.audit_query.extract_fhir_context"),
    ):
        instance = MockClient.return_value
        instance.search = AsyncMock(side_effect=fake_search)
        result_json = asyncio.run(query_audit_event(since="", drug_filter="naproxen", limit=10, ctx=None))

    result = json.loads(result_json)
    assert result["count"] == 1
    assert "naproxen" in result["events"][0]["description"].lower()


def test_query_audit_event_handles_fhir_error_gracefully():
    async def boom(rt, params):
        raise RuntimeError("FHIR connection lost")

    with (
        patch("tools.audit_query.FhirClient") as MockClient,
        patch("tools.audit_query.extract_patient_id", return_value="p"),
        patch("tools.audit_query.extract_fhir_context"),
    ):
        instance = MockClient.return_value
        instance.search = AsyncMock(side_effect=boom)
        result_json = asyncio.run(query_audit_event(ctx=None))

    result = json.loads(result_json)
    assert "error" in result
    assert "tool_execution_failed" in result["error"]
