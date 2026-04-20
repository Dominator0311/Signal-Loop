# Platform Research Notes

Findings from reading the `po-community-mcp` Python repo and Prompt Opinion docs. Use this as the definitive reference for how to build our MCP server and configure the BYO agent.

---

## MCP Server Architecture (from po-community-mcp/python)

### Stack
- **Framework:** FastAPI + `mcp` Python SDK (FastMCP)
- **Transport:** Streamable HTTP (mounted at `/`)
- **Dependencies:** `fastapi>=0.115.0`, `uvicorn>=0.32.0`, `mcp>=1.9.0`, `httpx>=0.28.0`, `PyJWT>=2.10.0`

### How it works

**main.py** — minimal FastAPI app:
```python
from mcp_instance import mcp

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
app.mount("/", mcp.streamable_http_app())
```

**mcp_instance.py** — server declaration + extension + tools:
```python
mcp = FastMCP("Python Template", stateless_http=True, host="0.0.0.0")

# FHIR context extension declaration (monkey-patches capabilities)
_original_get_capabilities = mcp._mcp_server.get_capabilities
def _patched_get_capabilities(notification_options, experimental_capabilities):
    caps = _original_get_capabilities(notification_options, experimental_capabilities)
    caps.model_extra["extensions"] = {"ai.promptopinion/fhir-context": {}}
    return caps
mcp._mcp_server.get_capabilities = _patched_get_capabilities

# Tool registration
mcp.tool(name="ToolName", description="...")(tool_function)
```

### SHARP Headers (from mcp_constants.py)

The platform sends these headers on every tool call when FHIR context is enabled:
```
x-fhir-server-url    → URL of workspace FHIR server
x-fhir-access-token  → Bearer token for FHIR server (optional)
x-patient-id         → Active patient ID (in patient-scope)
```

### How tools receive headers (from fhir_utilities.py)

```python
from mcp.server.fastmcp import Context

def get_fhir_context(ctx: Context) -> FhirContext | None:
    req = ctx.request_context.request
    url = req.headers.get("x-fhir-server-url")
    token = req.headers.get("x-fhir-access-token")
    return FhirContext(url=url, token=token)

def get_patient_id_if_context_exists(ctx: Context) -> str | None:
    req = ctx.request_context.request
    fhir_token = req.headers.get("x-fhir-access-token")
    if fhir_token:
        claims = jwt.decode(fhir_token, options={"verify_signature": False})
        patient = claims.get("patient")
        if patient:
            return str(patient)
    return req.headers.get("x-patient-id")
```

**Key insight:** Patient ID can come from either:
1. The JWT claims inside the access token (`patient` claim)
2. The `x-patient-id` header directly

Always check both.

### FHIR Client (from fhir_client.py)

Simple httpx-based client:
```python
class FhirClient:
    def __init__(self, base_url, token=None):
        ...
    async def read(self, path) -> dict | None:
        # GET {base_url}/{path} with Bearer token
    async def search(self, resource_type, search_parameters) -> dict | None:
        # GET {base_url}/{resource_type}?{params}
```

### Tool pattern (from sample tools)

```python
async def my_tool(
    patientId: Annotated[str | None, Field(description="...")] = None,
    ctx: Context = None,
) -> str:
    if not patientId:
        patientId = get_patient_id_if_context_exists(ctx)
        if not patientId:
            raise ValueError("No patient context found")

    fhir_context = get_fhir_context(ctx)
    if not fhir_context:
        raise ValueError("The fhir context could not be retrieved")

    fhir_client = FhirClient(base_url=fhir_context.url, token=fhir_context.token)
    # ... do FHIR operations ...
    return create_text_response("result text")
```

---

## FHIR Context Extension Declaration (from docs)

The extension can declare SMART scopes:
```json
{
  "capabilities": {
    "extensions": {
      "ai.promptopinion/fhir-context": {
        "scopes": [
          {"name": "patient/Patient.rs", "required": true},
          {"name": "patient/Condition.rs"},
          {"name": "patient/MedicationRequest.rs"},
          {"name": "patient/Observation.rs"},
          {"name": "patient/AllergyIntolerance.rs"}
        ]
      }
    }
  }
}
```

Scopes marked `required: true` cannot be unchecked by users.

---

## BYO Agent Configuration

### Setup path
Agents → BYO Agents → Add AI Agent

### Key configuration areas:
1. **Model** — must be configured first (via Model Configuration page)
2. **System prompt** — platform uses variables that get replaced at runtime; always check default template
3. **Response Format** — JSON Schema; provider-specific restrictions apply
4. **Tools** — attach MCP servers
5. **Content** — ground to ONE collection (or PubMed, or public collection)
6. **A2A** — enable with at least one skill; can require FHIR context extension
7. **Scope** — Patient (our choice), Workspace, or Group

### Important gotchas:
- System prompt has platform variables — review default with "Load Default" before customizing
- Each provider has different JSON schema restrictions
- One content collection only per agent
- Guardrails are pre-prompt only (no post-response yet)
- Agent appears in Launchpad based on scope selection

---

## Agent Scopes

- **Patient scope** — agent works with individual patient data. Appears when patient is selected in Launchpad.
- **Workspace scope** — unrestricted access to all workspace data.
- **Group scope** — works with a group of patients.

We use **Patient scope** for SignalLoop.

---

## Running Locally

```bash
cd signalloop-medsafe-mcp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then: `ngrok http 8000 --domain=YOUR-DOMAIN.ngrok.app`

Register in Prompt Opinion: Configuration → MCP Servers → Add → URL: `https://YOUR-DOMAIN.ngrok.app/mcp`

---

## What We Know Works

- FastMCP with streamable HTTP transport
- Monkey-patched capabilities for extension declaration
- FHIR reads via httpx with Bearer token
- Tool functions with `ctx: Context` parameter to access headers
- Patient ID from JWT or header fallback
- CORS with allow_origins=["*"]

## Open Questions (to verify when laptop available)

1. Can we return structured JSON from tools (not just text strings)?
2. Does the platform handle tool errors gracefully or does it crash?
3. How does the Response Format JSON schema interact with tool outputs?
4. What happens when we POST (write) to the FHIR server — same base URL + token?
5. Exact Gemini JSON schema limitations for our response format
