"""
MedSafe MCP Server — Entry Point.

SignalLoop MedSafe: A three-phase medication safety MCP server providing
context-aware prescribing safety for the Prompt Opinion platform.

Architecture:
  Phase 1 (LLM): Build patient risk profile from FHIR record
  Phase 2 (Rules): Deterministic safety check parameterised by profile
  Phase 3 (LLM): Synthesise patient-specific response with alternatives

Run: uvicorn main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server import mcp


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage MCP session lifecycle."""
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="SignalLoop MedSafe MCP",
    description="Three-phase medication safety server for Prompt Opinion",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount MCP server at root — Prompt Opinion expects tools at /mcp
app.mount("/", mcp.streamable_http_app())
