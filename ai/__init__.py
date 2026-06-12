"""Local-AI layer for the SME IT Agent.

Phase 1 (chatbot-first) runs the chat through Open WebUI, which talks to Ollama
directly and reaches our data via the FastAPI tool server (see webtools/). So the
only thing this package owns right now is the *prompt* that gives the model its
persona and guardrails (prompts.py). A programmatic Ollama client (brain.py) is
deferred to when the rule engine needs root-cause analysis on escalated events.
"""
