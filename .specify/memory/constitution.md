<!--
Sync Impact Report
Version change: template -> 1.0.0
Modified principles:
- Added I. Comprehensive Documentation
- Added II. Small Modular Functions
- Added III. Strict Error Handling
- Added IV. Shallow Control Flow
- Added V. Clinical IE Correctness and Testability
Added sections:
- Engineering Standards
- Development Workflow and Review Gates
Removed sections: none
Templates requiring updates:
- .specify/templates/plan-template.md: Constitution Check must list quality gates
- .specify/templates/spec-template.md: Edge cases and requirements must capture error handling
- .specify/templates/tasks-template.md: Tasks must include docstrings, modularity, error handling, nesting review
Follow-up TODOs: none
-->

# ViClinicalIE Constitution

## Core Principles

### I. Comprehensive Documentation

All new production code MUST include comprehensive docstrings. Public modules, classes, functions, methods, scripts, and pipeline entry points MUST document purpose, inputs, outputs, side effects, raised exceptions, and clinical text assumptions when relevant. Docstrings MUST explain non-obvious Vietnamese clinical language rules, offset handling, assertion logic, normalization behavior, and deterministic extraction decisions. Inline comments SHOULD explain complex rules or medical-domain edge cases, but MUST NOT replace docstrings.

### II. Small Modular Functions

Every new or modified function MUST remain under 50 logical lines, excluding blank lines, comments, and docstrings. Any behavior that would exceed this limit MUST be decomposed into named helper functions with single responsibility. Helpers MUST expose clear inputs and outputs and avoid hidden mutation unless explicitly documented. Large procedural blocks, multi-purpose utilities, and mixed parsing/extraction/output logic are prohibited.

### III. Strict Error Handling

All new code MUST handle expected failures explicitly. File I/O, parsing, model loading, JSON serialization, offset calculation, external dependencies, and user-provided input MUST validate preconditions and surface actionable errors. Broad exception swallowing is prohibited. `except Exception` is allowed only at top-level boundaries where errors are logged or converted into clear failure reports. Error messages MUST include enough context to diagnose the failing input, path, section, span, or pipeline stage without exposing sensitive clinical content beyond what is necessary.

### IV. Shallow Control Flow

Deep nesting is prohibited. New code MUST keep control flow shallow through guard clauses, early returns, small helpers, table-driven rules, or strategy functions. More than three nested control structures in one function requires refactoring before merge. Complex boolean conditions MUST be named or split so reviewers can verify clinical logic and edge cases. Nested loops over clinical text spans MUST document ordering and overlap assumptions.

### V. Clinical IE Correctness and Testability

Clinical information extraction behavior MUST be deterministic, offset-safe, and independently testable unless a feature explicitly introduces model-based behavior with documented evaluation criteria. Changes to section parsing, span extraction, assertions, overlap resolution, normalization, or output formatting MUST include tests or documented verification steps that cover positive cases, negative cases, boundary offsets, and malformed input. Generated outputs MUST preserve source text traceability and avoid silent data loss.

## Engineering Standards

- New Python code MUST use type hints for function signatures where practical.
- Functions MUST have one reason to change and one clear abstraction level.
- Validation MUST occur at system boundaries before data enters core extraction logic.
- Logging MUST be structured enough to identify pipeline stage and record identifier.
- Deterministic rules MUST be named and documented with examples when they encode medical or Vietnamese-language assumptions.
- Temporary complexity is allowed only with documented justification, owner, and removal plan in the implementation plan.

## Development Workflow and Review Gates

Before implementation starts, every plan MUST pass these gates:

1. Documentation gate: all new code paths identify required module/class/function docstrings.
2. Modularity gate: planned functions can remain under 50 logical lines, with helper boundaries named for complex logic.
3. Error-handling gate: expected failure modes and validation points are listed.
4. Nesting gate: design avoids more than three nested control structures through guard clauses or decomposition.
5. Clinical correctness gate: tests or verification steps cover offsets, malformed input, assertions, and output traceability when relevant.

During review, any violation blocks merge unless documented in Complexity Tracking with a safer alternative rejected for a concrete reason and a remediation task scheduled. Refactoring to satisfy this constitution takes priority over adding additional feature scope.

## Governance

This constitution supersedes conflicting local practice, generated plans, and task templates. All specifications, plans, tasks, code reviews, and implementation work MUST verify compliance with these rules. Amendments require a written rationale, review of affected templates, migration notes for existing code if applicable, and semantic version update.

Version policy:
- MAJOR: incompatible governance change or removal/redefinition of a core principle.
- MINOR: new principle or materially expanded requirement.
- PATCH: wording clarification, typo fix, or non-semantic template sync.

Existing code is not automatically non-compliant, but any touched function MUST be brought into compliance when practical. If full compliance is unsafe for a change, the plan MUST document the exception, risk, and follow-up remediation.

**Version**: 1.0.0 | **Ratified**: 2026-07-12 | **Last Amended**: 2026-07-12
