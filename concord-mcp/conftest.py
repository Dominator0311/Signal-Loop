import sys
from pathlib import Path

# Add concord-mcp/ root to Python path so tests can import rules/, llm/, tools/
sys.path.insert(0, str(Path(__file__).parent))
