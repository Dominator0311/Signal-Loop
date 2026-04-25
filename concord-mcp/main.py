"""
Concord MCP Server — Entry Point.

Concord: A multi-specialist clinical conflict resolver. Coordinates nephrology,
cardiology, and pharmacy specialist agents and provides deterministic arbitration
tools for producing a unified, validated care plan.

Run: uvicorn main:app --reload --port 8001
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server import mcp


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Concord MCP",
    description="Multi-specialist conflict resolver for Prompt Opinion",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "service": "concord-mcp"})


app.mount("/", mcp.streamable_http_app())
