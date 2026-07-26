# Agents Notes - hexnut-blog-tool (Python)

This file applies to the hexnut-blog-tool project.
Read it before making changes.

## Context
- Tool for preparing and publishing technical articles from git-backed Markdown to Blogger (hexnut.net).
- Focus: deterministic, simple, readable Python.
- Philosophy: minimal abstractions, clear contracts, easy for students to understand.

## Project shape
- Content lives under `content/<lang>/...`
- Assets (images) under `assets/`
- Python code under `scripts/` (small modules)
- One public CLI entry, thin wrappers around external APIs.
- Keep experiments / features minimal and self-contained.

## Coding conventions (adapted CLASS + Scalable principles for Python)
- snake_case for functions, variables, files
- UPPER_CASE for constants and config keys
- 4 spaces indent
- Keep modules small, cohesive, independently testable
- Prefer plain functions + dataclasses / simple dicts over deep class hierarchies
- No global mutable state
- Explicit paths and ownership (caller provides buffers/paths where possible)
- Minimal dependencies — only add when measured need exists
- Use type hints where they improve readability
- Assert-heavy on preconditions (contract violations are bugs)

Every non-trivial function has a short comment or docstring:
  # Why: ...
  # What: ...
  # Pre: ...
  # Post: ...

## Design By Contract
- Check preconditions at function entry.
- Fail fast on invalid caller input (assert, clear exception, or explicit error return).
- Never silently fix bad input.
- Distinguish programming errors from expected runtime failures (e.g. network).
- For runtime failures return clear result objects or raise documented exceptions.

## LLM & external services
- Isolate all LLM calls (Grok/xAI) in llm.py
- Isolate Blogger API in blogger.py
- Make prompts and error handling explicit and reviewable.
- Never log API keys or full content of user articles.

## Build / Run / Test
- Use `python -m scripts ...`
- `pip install -r requirements.txt`
- `pytest` for all public behaviour
- Document exact commands to reproduce in README and commit messages
- Support --dry-run for publish operations

## Change Discipline
- Read existing code and tests before editing.
- Keep changes scoped.
- Do not remove contracts, comments or tests to "clean up".
- Update README and verification commands when behaviour changes.
- Preserve the NL summary + English structure in README.md

## Verification
Every change must document:
- exact commands to build/run/test the change
- expected output for a minimal case

## Notes
- This project supports Python experiments in the larger repo.
- Adapt these rules if they conflict with teaching goals.
- Keep everything git-backed and reproducible.
