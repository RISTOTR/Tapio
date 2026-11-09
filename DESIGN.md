---
name: TAPIO
description: Restrained, functional, evidence-oriented personal data workspace.
---

## Overview

This is the user-confirmed design direction, implemented incrementally in the
shared workspace shell, Ask and Review. Preserve existing behavior
and safety logic. PRODUCT.md owns product facts; docs/design/workspace.md owns
the target workflow's screen guidance.

Calm, trustworthy, practical and professional. Nordic restraint means clear
structure and economical decoration, not themed imagery. Repeated daily/monthly
use takes priority over novelty. The signature is a scan-friendly record with
its amount, context, current authority and supporting evidence close together.

Existing source baseline: tapio/pilot/page.html uses system-ui type, a narrow
reading column, simple controls and expandable evidence. The confirmation page
uses system-ui type, bordered review articles and explicit preview/apply controls.
These are implementation observations, not an endorsement of every current style.
Shared styles and evidence components live in tapio/pilot/workspace.css and
workspace.js; workspace.py composes the shared navigation. Desktop and narrow
layouts are verified with real-browser fixtures. Import and Summary remain
explicit placeholders.

## Colors

Use quiet neutral surfaces, readable text and restrained functional accents.
Reserve status color for meaningful state and always pair it with text or symbols.
Keep personal, property and forestry labels explicit rather than color-only.
Avoid generic AI gradients and neon colors. Exact palette values remain open;
this context file does not introduce unverified normative color tokens.

## Typography

Retain system-ui as the existing practical baseline. Use a compact, readable
hierarchy with ordinary page and section headings, not oversized marketing type.
Align monetary values consistently, use tabular numerals where available and
keep currency, signs, units and dates unambiguous. Do not gain density by making
essential evidence or labels difficult to read. Formatting/localization details
remain open and must not change underlying numeric meaning.

## Layout

Desktop-first and responsive. Prefer tables, structured rows and compact panels
with predictable columns and clear section boundaries. Use whitespace to group
related records and distinguish actions, rather than wrapping everything in cards.
Keep important evidence adjacent to the answer or decision it supports.

On narrow screens preserve field relationships, labels and decision context;
allow local table scrolling when needed without making the whole page overflow.
Support zoom, wrapping long references and keyboard access to overflow content.
Navigation should support repeated task switching rather than a chatbot-centric
layout. The target screen sequence is specified in the workspace brief.

## Elevation & Depth

Use restrained borders and surface separation. Avoid glassmorphism, decorative
shadows and dashboard ornament without a functional purpose. Motion should only
communicate a useful state change, respect reduced-motion preferences and never
delay reading or reviewing records.

## Shapes

Use simple control and panel shapes compatible with the existing application.
Avoid ornamental containers and excessive card framing. Shared radius and spacing
values remain implementation decisions; do not invent a token system in this file.

## Components

Use semantic tables for comparable records, structured rows for review items,
compact panels for related facts, and labelled form controls for decisions.
Existing preview/apply behavior and current-state authority are binding.

Keep the concise answer, material limitations and source summary visible.
Expandable details may hold supporting records and technical diagnostics, but
must not conceal evidence required to understand or approve a decision.

Distinguish loading, no results, no action needed, missing evidence, stale state,
read-only mode and failed requests. A failed load must never look like an empty
queue or a zero amount. Show current decisions separately from original suggestions.

## Do's and Don'ts

- Prefer scanability, readable contrast and keyboard-visible focus.
- Show financial amounts, dates, context, provenance and decision state clearly.
- Preserve semantic concepts, user rules and individual/grouped review access.
- Preserve explicit confirmation and auditability when reducing manual effort.
- Avoid excessive cards, generic AI gradients, glassmorphism, neon, oversized
  marketing typography, unnecessary animation and decorative dashboard widgets.
- Do not turn TAPIO into a chat-first interface or bury important evidence behind
  multiple disclosures.
- Do not redesign the backend, remove safety checks, fabricate data or imply tax
  conclusions from a category or context label.
