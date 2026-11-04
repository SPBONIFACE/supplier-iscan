"""The LLM evaluation harness (#22): `make eval`.

Run from `backend/` (its environment holds the dependencies): `python -m eval`. Reference sets
are plain JSON; the model answers recorded in them serve the fake provider only (plumbing, never
model quality). Everything reaches a model through the #11 interface and the #19 redaction gate.
"""
