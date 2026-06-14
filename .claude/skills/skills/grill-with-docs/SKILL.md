---
name: grill-with-docs
description: Grilling session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, ADRs) inline as decisions crystallise. Use when user wants to stress-test a plan against their project's language and documented decisions.
---

<what-to-do>

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing.

If a question can be answered by exploring the codebase, explore the codebase instead.

</what-to-do>

<supporting-info>

## Domain awareness

During codebase exploration, also look for existing documentation:

### File structure

Most repos have a single context:

```
/
├── CONTEXT.md
├── docs/
│   └── adr/
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
└── src/
```

If a `CONTEXT-MAP.md` exists at the root, the repo has multiple contexts. The map points to where each one lives:

```
/
├── CONTEXT-MAP.md
├── docs/
│   └── adr/                          ← system-wide decisions
├── src/
│   ├── ordering/
│   │   ├── CONTEXT.md
│   │   └── docs/adr/                 ← context-specific decisions
│   └── billing/
│       ├── CONTEXT.md
│       └── docs/adr/
```

Create files lazily — only when you have something to write. If no `CONTEXT.md` exists, create one when the first term is resolved. If no `docs/adr/` exists, create it when the first ADR is needed.

## Glossary format (CONTEXT.md)

Keep CONTEXT.md strictly as a glossary of domain terms. Do not add architecture specs, plans, or scratchpad notes.

Example:

```markdown
# Context: Ordering

## Glossary

### Order
A collection of items requested by a customer...

### Line Item
A single product and quantity within an order...
```

## Decisions format (docs/adr)

Keep ADRs simple. Don't add boilerplate metadata unless the user's custom template specifies it.

Example:

```markdown
# 1. Event Sourced Orders

We will event source the Ordering domain model.

## Context

We need a complete audit trail of order states...

## Decision

We will store order events in PostgreSQL...

## Consequences

- Full audit trail of all order changes
- Higher complexity in querying current state (requires projection)
```

</supporting-info>
