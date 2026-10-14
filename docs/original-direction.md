# Final Product Direction --- AI Reader Companion for Complex Fantasy Series

## 1. Product Vision

### Core positioning

**"Never lose the plot."**

Build a **private, AI-powered reading companion for complex
speculative-fiction series**---especially long series of 15--20+ books
where characters, factions, locations, magic systems, events, mysteries,
aliases, and relationships become difficult to track.

The product is **not primarily a traditional wiki**. The wiki is the
underlying knowledge model; the user-facing product is a
**reader-position-aware companion**.

The central promise:

> **Tell me what I need to know right now, without spoiling anything I
> have not read.**

### Core product insight

The moat is a **longitudinal, evidence-backed model of a fictional
universe tied to the reader's exact reading position**.

The product should understand:

-   What the reader has reached.
-   What information is legitimately available at that point.
-   What is known, suspected, inferred, contradicted, or unresolved.
-   Where each piece of information came from.
-   How entities and events evolve across a long series.

The reader should be able to ask questions naturally rather than
manually maintain a wiki.

### Reader horizon

The fundamental privacy/spoiler boundary is the reader's **exact reading
horizon**:

-   Series
-   Book
-   Chapter
-   Passage / finer-grained position when available

The system must answer using information available **at or before that
horizon**, unless the user explicitly changes the horizon.

Spoiler safety is therefore a **data-model and retrieval constraint**,
not merely a UI warning.

### Core jobs-to-be-done

The initial product should excel at:

1.  **"Who is this?"**
    -   Identify a character, alias, place, faction, object, etc.
    -   Explain what the reader knows about it *so far*.
2.  **Recap**
    -   "What happened recently?"
    -   "Remind me what happened in the previous book."
    -   "What do I need to remember before starting this chapter?"
3.  **Relationship/context questions**
    -   Who is connected to whom?
    -   Why does this character matter?
    -   Where have I encountered this person before?
4.  **Mystery tracking**
    -   What questions are currently unresolved?
    -   What clues/evidence have appeared so far?
    -   What theories are supported versus merely possible?
5.  **Search**
    -   Search the imported books and the derived knowledge model while
        respecting the reading horizon.
6.  **Evidence**
    -   Show where an answer came from.
    -   Distinguish direct textual evidence from inference.

### Knowledge philosophy

The system should **preserve uncertainty rather than flattening it**.

Important distinctions include:

-   Directly stated
-   Observed
-   Inferred
-   Suspected
-   Rumored / in-world claim
-   Contradicted
-   Unknown
-   Unresolved

Contradictions are data, not necessarily extraction failures.

The system should be able to say, in effect:

> "Here is what the text establishes so far; here is what a character
> believes; here is what the evidence suggests; and here is what remains
> unknown."

### Dynamic world model

The product must work across different fictional universes without
requiring a custom schema for every series.

The ontology should therefore be **dynamic and data-driven**.

It must be capable of discovering and representing different kinds of:

-   Characters
-   Aliases
-   Places
-   Objects
-   Factions
-   Events
-   Relationships
-   Abilities
-   Rules
-   Mysteries
-   Beliefs
-   Systems of magic/power

The magic/power model must be flexible enough to extract **soft, hard,
and crunchy systems** without redesigning the application for each
series.

### Privacy / processing philosophy

The intended architecture is **local/private-first**.

The user's books and derived knowledge should be able to remain local,
with AI processing performed locally where practical.

The architecture should nevertheless allow a replaceable compute
layer/provider so that the product is not permanently coupled to one
local model or inference runtime.

The product is intended to be web-enabled where useful, but the core
personal library and knowledge model should remain under the user's
control.

------------------------------------------------------------------------

# 2. Marketing Plan

## Positioning

### Primary message

**Never lose the plot.**

### Category framing

Do not lead with:

-   "Build your own wiki"
-   "AI wiki"
-   "Worldbuilding database"
-   "Notion for fantasy"
-   "Graph database for authors"

Those describe implementation or adjacent categories rather than the
strongest user value.

Lead with:

> **A private AI reading companion for complex fantasy and
> speculative-fiction series.**

### Target customer

The initial audience is the **reader of complex, long-form speculative
fiction**, particularly readers who:

-   Read multi-book series.
-   Regularly forget names and relationships.
-   Need recaps between books.
-   Want to understand mysteries without having them spoiled.
-   Search the internet and risk encountering spoilers.
-   Have tried wikis but find them spoiler-heavy, cluttered, ad-heavy,
    or cumbersome.
-   Want deeper context than a conventional ebook's search function
    provides.

A strong initial niche is readers of large, interconnected
fantasy/science-fiction universes.

## Competitive positioning

### Fandom

Fandom demonstrates demand for searchable fictional-universe knowledge,
but its weaknesses create an opening:

-   Advertising/clutter.
-   Spoiler exposure.
-   Information is organized as a public wiki rather than around the
    reader's current position.
-   The user must know what page to visit and what is safe to read.

**Our advantage:** private, reader-position-aware, spoiler-safe answers
generated from the user's own books.

### LegendKeeper

LegendKeeper validates the value of structured fictional-universe
knowledge and attractive worldbuilding organization.

Its center of gravity is **worldbuilding/knowledge management**.

**Our advantage:** the primary workflow is reading comprehension and
continuity across published books, not manually authoring a world bible.

### Obsidian

Obsidian demonstrates the appeal of a flexible local knowledge base and
graph-oriented thinking.

Its center of gravity is a general-purpose personal knowledge-management
tool.

**Our advantage:** the user does not have to manually create links,
structure notes, maintain entities, or enforce spoiler boundaries. The
product builds the useful structure from the books.

### Strategic differentiation

The product should not attempt to beat all three competitors at their
own game.

It should own this specific intersection:

> **Long-series reading + AI understanding + exact reading horizon +
> evidence + spoiler safety + private/local data.**

That is the core differentiation.

## Marketing funnel

### Hook

**Never lose the plot.**

### Demonstration

Show a reader at a specific point in a book asking:

> "Who is this person again?"

The system answers with only information available up to that point and
shows the supporting passages.

Other high-value demonstrations:

-   "What happened in the last book?"
-   "What do I know about this character so far?"
-   "What mysteries are still unresolved?"
-   "Where have I seen this name before?"
-   "What does the magic system appear to allow at this point?"

### Trust-building

Marketing should emphasize:

-   No accidental spoilers.
-   Evidence-backed answers.
-   Reader-controlled data.
-   Private/local processing.
-   The distinction between facts, inference, and uncertainty.

### Initial acquisition strategy

Prioritize communities where readers of complicated series already
discuss:

-   Series-specific reading problems.
-   Character confusion.
-   Recaps.
-   Spoiler avoidance.
-   Reading orders.
-   Long-series recommendations.

The product should be demonstrated through **real reading scenarios**,
not generic AI claims.

### Marketing principle

The product's strongest marketing asset should be the **"before/after"
reading experience**:

> "I used to search a wiki and risk spoilers. Now I ask my companion
> exactly where I am in the book."

------------------------------------------------------------------------

# 3. Design Direction

## Product experience

The UI should feel like a **reading companion first**, not a database
administration tool.

The primary interaction should be:

1.  Select/open a series.
2.  Set or confirm reading position.
3.  Ask a question or browse context.
4.  Receive a concise answer.
5.  Expand into evidence and deeper context when desired.

## Reader position should be persistent and obvious

The current reading horizon should be visible and easy to change.

The interface should make it difficult to accidentally search beyond the
reader's position.

The user should be able to intentionally move their horizon forward when
they finish a chapter/book.

## Answers first; graph second

Do not make the knowledge graph the main interface.

The graph is valuable infrastructure and a useful secondary
visualization, but most readers want an answer, not a graph.

Use the structured model to power:

-   Search
-   Recaps
-   Entity pages
-   Relationship context
-   Mystery tracking
-   Evidence
-   Spoiler filtering

## Evidence should be inspectable

Every important generated claim should be traceable back to source
material.

The UI should support a progression such as:

**Answer → supporting evidence → source passage**

This builds trust and lets the user verify the model.

## Epistemic status should be visible but not overwhelming

The UI should communicate uncertainty where it matters without turning
every answer into a technical research report.

Examples:

-   Confirmed
-   Inferred
-   Character belief
-   Unresolved
-   Contradictory

## Avoid premature feature expansion

The initial design should **not** be dominated by:

-   Full wiki authoring.
-   Elaborate graph editing.
-   Community features.
-   Public publishing.
-   Large map systems.
-   Extensive manual ontology configuration.

Those may become valuable later, but they should not distract from the
core reader experience.

------------------------------------------------------------------------

# 4. Architecture

## Architectural principle

The core pipeline is:

**Books → Evidence → Observations → Versioned Knowledge Graph →
Reader-Horizon Views → Answers**

The system should preserve the underlying source material and derived
knowledge rather than replacing the source with an opaque AI summary.

## Source layer

Imported books are immutable source material.

Initial supported input:

-   **EPUB**
-   DRM-free books that the user legally possesses

The original text should remain available as the authoritative evidence
layer.

## Evidence layer

The system should break source material into addressable evidence units
such as:

-   Book
-   Chapter
-   Passage
-   Text span

Every extracted fact should retain provenance pointing back to source
evidence.

## Observation / extraction layer

AI processing extracts observations from the text.

Observations should be treated as derived claims, not unquestionable
truth.

Each observation should be able to retain:

-   Entity references
-   Relationship/event references
-   Source location
-   Confidence
-   Epistemic status
-   Temporal/book position
-   Extraction provenance

## Knowledge graph

The knowledge graph is **versioned and temporal**.

It should represent how the fictional universe appears at different
points in the series.

The graph should support:

-   Entities
-   Aliases
-   Relationships
-   Events
-   Locations
-   Objects
-   Factions
-   Abilities
-   Rules
-   Mysteries
-   Beliefs
-   Contradictions
-   Time / narrative position

## Dynamic ontology

Ontology is data, not hard-coded application logic.

The system should be capable of creating or extending entity and
relationship types based on the material it encounters.

This is critical for supporting different genres and different styles of
magic/power systems without redesigning the database.

## Reader-horizon projection

The user's current reading position produces a **safe view** of the
knowledge model.

The answer engine should query this view rather than simply querying the
full underlying graph.

This is the architectural mechanism that makes spoiler safety
enforceable.

## AI / compute architecture

Use a replaceable AI worker/provider architecture.

The first implementation can use local AI tooling such as:

-   **Ollama** for local model execution.
-   A separate compute/worker layer so the application is not tightly
    coupled to Ollama.

This allows future support for different local models or other providers
without rebuilding the product.

## Backend

Initial backend direction:

-   **Python / FastAPI**
-   **PostgreSQL**
-   **pgvector** where semantic retrieval is useful

PostgreSQL is the primary system of record.

Vector search is an aid to retrieval, not the canonical knowledge store.

## Frontend

Initial direction:

-   **React**
-   Web application first

The frontend should communicate with the API rather than embedding
domain logic into the client.

## Core data principle

Do not make an LLM-generated summary the canonical representation.

Canonical data should be:

**source text + evidence + structured observations + provenance +
versioned knowledge**

Generated summaries/answers are views over that data.

------------------------------------------------------------------------

# 5. Development Plan

## Phase 0 --- POC

The POC is intended to answer one question:

> **Can the system reliably turn a real long-form fantasy book into a
> useful, spoiler-safe, evidence-backed reader companion?**

The POC should be deliberately narrow.

### POC input

-   One or a small number of DRM-free EPUBs.
-   At least one genuinely complex fantasy/speculative-fiction example.
-   Enough material to test cross-chapter and cross-book continuity.

### POC capabilities

The POC should demonstrate:

1.  EPUB ingestion.
2.  Chapter/passage segmentation.
3.  Source indexing.
4.  Entity extraction.
5.  Alias resolution.
6.  Basic relationships.
7.  Event extraction.
8.  Provenance back to passages.
9.  Reader-position filtering.
10. Question answering constrained to the reader horizon.
11. Evidence display.
12. Basic uncertainty/epistemic labeling.
13. Basic recap generation.
14. Basic "Who is this?" functionality.

### POC architecture

**EPUB → parser → passages → extraction → observations →
PostgreSQL/pgvector → horizon-filtered retrieval → local LLM → answer +
citations**

### What the POC should prove

The POC succeeds if it demonstrates that:

-   A real book can be ingested with sufficiently useful structure.
-   Characters and aliases can be resolved with acceptable accuracy.
-   Important relationships/events can be extracted.
-   Answers can reliably cite source passages.
-   The system can answer questions using only information available at
    the reader's current position.
-   The resulting answers are genuinely useful to a reader.
-   The architecture works without manually designing a custom schema
    for the test series.

### Critical POC test

The most important test is **spoiler isolation**.

Given a known reading position, deliberately ask questions whose
complete answers occur later in the book/series.

The system must not leak later information.

This should be treated as a hard product requirement, not a
nice-to-have.

------------------------------------------------------------------------

# 6. If the POC Succeeds

## Phase 1 --- MVP

Turn the POC into a usable private reader product.

### MVP scope

-   Multi-book series.
-   Persistent reader position.
-   Characters and aliases.
-   Locations.
-   Events.
-   Relationships.
-   Objects/factions where useful.
-   Reader-position-aware search.
-   "Who is this?"
-   Recaps.
-   Mystery/unresolved-question tracking.
-   Evidence and source passages.
-   Epistemic status.
-   Contradiction handling.
-   Local/private AI processing.
-   Clean web UI.
-   Import and processing status.

### MVP philosophy

The MVP should remain focused on **reading assistance**, not become a
general-purpose wiki builder.

------------------------------------------------------------------------

# 7. Post-MVP Expansion

Only after the core reader experience is validated should the product
expand toward broader knowledge-management functionality.

Potential later layers include:

-   Rich entity pages.
-   Interactive relationship graphs.
-   Maps and spatial relationships.
-   More sophisticated magic/system modeling.
-   Timeline exploration.
-   User annotations.
-   Manual corrections.
-   Better cross-book synthesis.
-   Optional sharing/publication.
-   Community features.
-   Author/worldbuilder workflows.
-   Additional import formats.
-   More advanced AI models/providers.

These are extensions of the underlying knowledge model, not requirements
for the initial product.

------------------------------------------------------------------------

# 8. Decisions / Non-Decisions

## Decided

-   **Positioning:** reader companion, not primarily a wiki.
-   **Core promise:** "Never lose the plot."
-   **Target:** readers of complex, long speculative-fiction series.
-   **Key differentiator:** exact reading horizon + AI + evidence +
    spoiler safety + private/local data.
-   **Source-first architecture:** books remain authoritative.
-   **Knowledge model:** evidence-backed, versioned, temporal graph.
-   **Ontology:** dynamic/data-driven.
-   **Uncertainty:** preserved explicitly.
-   **Contradictions:** retained rather than flattened.
-   **Initial import:** DRM-free EPUB.
-   **AI:** local/private-first with replaceable compute layer.
-   **Backend:** FastAPI + PostgreSQL/pgvector.
-   **Frontend:** React/web.
-   **POC:** prove useful, evidence-backed, spoiler-safe answers from
    real books before broad product development.
-   **Development strategy:** narrow POC → focused reader MVP → broader
    features only after validation.

## Explicitly Deferred

-   Full public wiki platform.
-   Community editing.
-   Public publishing.
-   Elaborate graph-first UX.
-   Full map tooling.
-   Large manual ontology editor.
-   Author/worldbuilding-first positioning.
-   Broad multi-purpose knowledge-management functionality.

## Strategic rule

Every proposed feature should answer one of two questions:

1.  **Does this make the reader better at understanding a complex series
    at their current reading position?**
2.  **Does this strengthen the underlying evidence-backed universe model
    that enables that experience?**

If not, it should not be part of the initial product.
