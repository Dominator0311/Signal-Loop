"""
LLM prompts as first-class artifacts.

Each prompt module contains the system instruction and prompt templates
for a specific Phase 1 or Phase 3 capability. Prompts are iterable
independently of tool logic — you can improve a prompt without touching
the tool implementation.
"""
