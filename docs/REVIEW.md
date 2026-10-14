# Review of the Product Direction

A critical review of [`original-direction.md`](original-direction.md), the plan drafted with ChatGPT. It covers what holds up, what is missing, what is overbuilt, and a response to each of the four known challenges.

Date: 2026-10-14

> **Update:** later decisions are in [DECISIONS.md](DECISIONS.md) and
> [ARCHITECTURE.md](ARCHITECTURE.md), and they take precedence over this review.
> The main change: no LLM is called at reading time. That removes the
> reading-time parametric leak described in §3.3. The same risk now applies at
> ingestion, where it is handled by the quote check.

---

## 1. TL;DR

- **The core idea is sound, and it now has proof of demand.** Amazon shipped
  *Ask this Book* (Dec 2025): a spoiler-limited Q&A that runs inside the Kindle
  iOS app. It also shipped *Kindle Recaps* for series. Both confirm that people
  want this. Both also mean the plain "spoiler-free Q&A" pitch is no longer
  unique on its own.
- **The strongest remaining angle is the indie-author niche, not general
  readers.** Authors cannot opt out of Amazon's feature, and some are unhappy
  about it. A companion that authors consent to, and that covers indie series
  with no wiki, is something Amazon is structurally unlikely to offer.
- **The architecture is over-specified for a POC.** A "versioned temporal
  knowledge graph with dynamic ontology" is the right long-term shape. It is
  the wrong first build. Start with a spoiler-safe retrieval-plus-summaries
  baseline, and make the graph earn its place by beating that baseline.
- **The spoiler model is missing its hardest cases.** Filtering retrieval by
  position is not enough. Alias reveals, entity summaries built from the
  whole series, and the LLM's own memory of famous books all leak spoilers
  even when retrieval is perfectly filtered. See §3.
- **Compute is less of a blocker than it looks.** Ingestion is a one-time
  overnight batch job, not interactive work. Questions at reading time are
  cheap. See §5.3.
- **Getting reading position is solvable without OCR heroics.** Pick a
  chapter, then refine it by sharing or pasting a sentence. Users of KOReader
  or the app's built-in reader get an exact position for free. See §5.4.
- **A practical blocker the doc misses:** much indie fantasy (LitRPG,
  progression fantasy) is *Kindle Unlimited exclusive*, which means it has
  DRM and no EPUB is available. That shapes which authors and readers you can
  serve. See §5.2.

---

## 2. What the original direction gets right

These ideas should be kept as they are:

1. **Reader companion, not a wiki.** This is the correct product framing. The
   wiki is a view over the data, not the product.
2. **Spoiler safety as a data-model constraint**, not a UI warning. This is
   the single most important architectural idea in the document.
3. **The source text stays canonical; generated summaries are views.** This
   keeps everything re-derivable when models improve, which they will, every
   few months.
4. **Evidence and provenance on every claim.** Citations build trust, and they
   also make spoiler leaks *mechanically checkable* (see §3.5).
5. **Preserve uncertainty.** "Character X believes Y" is different from "Y is
   true". This matters a lot in mystery-heavy fantasy.
6. **A replaceable compute layer.** This is cheap to do from day one (see §6).
7. **A narrow POC with spoiler isolation as a hard test.** This is the right
   instinct.
8. **The strategic rule** (every feature must improve comprehension at the
   current position, or strengthen the model behind it). This is a good filter
   for scope.

---

## 3. The spoiler model needs to go deeper

The document says the answer engine should "query a horizon-filtered view". That covers the obvious leak, where retrieval pulls a passage from chapter 40 while you are on chapter 12. There are at least five less obvious leaks:

### 3.1 Alias and identity reveals

If the graph merges "the Dread Pirate Roberts" and "Westley" into one entity
node, then *showing that node* is a spoiler, no matter which passages are
filtered. Identity is information that changes over time.

**Rule:** an alias link (`mention → entity`) has its own `established_at`
position: the point where the text makes the identity knowable. Before that
position, the two names are separate entities to the reader. Entity
resolution must be *incremental and in reading order*, never a global
clustering pass over the whole series.

### 3.2 Derived artifacts built from future text

An entity profile ("Kaladin is a former surgeon's apprentice turned …") that
was generated from all books leaks spoilers, even if every *citation* you show
is early.

**Rule (the single invariant that makes everything else safe):**
> Every stored derived artifact (summary, profile, observation, alias link, embedding cluster) records `max_source_pos`, the furthest position of any input used to build it. An artifact is visible only if `max_source_pos ≤ horizon`.

This turns the "versioned temporal graph" from an abstract idea into one
column and one `WHERE` clause.

### 3.3 The model's own memory (parametric leakage)

For popular series such as *Wheel of Time*, *Stormlight*, or *Malazan*, the LLM
has already read the wiki. Even with perfectly filtered context, it may "helpfully" add knowledge from later in the series.

Mitigations:
- Answer only from the retrieved context, and require a citation for each claim.
- Check each answer sentence against its cited passages. Drop sentences that
  have no support.
- Interesting side effect: **this risk is far lower for small indie series**,
  because models mostly don't know them. Your target niche is also the safest
  one.
- Measure the leak rate directly. Run the same eval on a famous series and on
  an obscure one.

### 3.4 The edge of the current chapter

If the reader's horizon is "chapter 12", have they finished chapter 12 or just
started it? The default should be **conservative**: horizon = end of the last
*completed* chapter, unless the position was refined to a specific passage.
Unsafe rounding is a bug, not a UX choice.

### 3.5 Leaks you can check mechanically

Because every claim cites passages that have positions, there are two kinds
of check:
- **Hard check (automatic, free):** no cited passage may be after the
  horizon. This catches retrieval and filtering bugs.
- **Soft check (eval set):** does the answer *contain* a fact from after the
  horizon, even without a citation? This catches parametric leaks and leaks
  from derived artifacts. It needs a hand-written test set (see PLAN.md
  Phase 0).

---

## 4. What is overbuilt for a first version

| Doc proposes | Recommendation for POC |
|---|---|
| Versioned temporal knowledge graph | Append-only `observation` rows with a position, plus the `max_source_pos` invariant. "Versioning" = filter by position. No graph DB. |
| Dynamic ontology | Entity/relationship `type` as a free-text string, plus a JSONB `attributes` column. Normalize types later by clustering. Don't design an ontology engine. |
| Soft/hard/crunchy magic system modeling | Defer. It falls out of free-text observations ("ability", "rule", "cost"). LitRPG stat blocks are a special case to look at later. |
| 8 epistemic statuses | Start with 3: **stated**, **claimed-by-character**, **inferred**. Add more once real data shows the need. |
| Contradiction handling | Defer. Store both observations; don't reconcile. |
| FastAPI + React + Postgres for the POC | CLI + eval harness first. The first UI should be a thin mobile web page, because people read on their phones. |
| Mystery tracking | A great feature, but the hardest one to extract reliably. Do it after "who is this" and recaps work. |

**The most important missing step:** a **baseline**. Before building any
extraction, build *horizon-filtered hybrid search (keyword + vector) + rolling
chapter summaries + cited Q&A*. That could deliver 60–80% of the value at 10%
of the effort. The structured layer is justified only where it beats the
baseline on the eval set: probably "who is this" (alias handling),
relationships, and cross-book entity history.

**Rolling summaries are spoiler-safe by construction.** The chapter N summary
is generated from chapter N plus the summary of chapters < N. Book recaps are
built from chapter summaries. This alone covers the "Recap" job.

---

## 5. The four stated challenges

### 5.1 Competitors

The doc compares against Fandom, LegendKeeper, and Obsidian. Those are
*adjacent* products. The **real** competitors are:

| Competitor | Threat | Gap you can own |
|---|---|---|
| **Kindle "Ask this Book"** (Dec 2025, iOS Kindle app, US, thousands of titles) | High. Spoiler-limited Q&A built into the dominant reader, at zero friction. | Kindle only. Authors can't opt out, and some are angry about it. Not every title is covered. Unclear how far it reasons across books in a series. No evidence/citation UX reported. Not available for EPUB, Kobo, KOReader, or web serials. |
| **Kindle Recaps** | Medium. Series recaps. | Not position-aware within a book. Carries spoiler warnings. Kindle titles only. |
| **Kindle X-Ray** | Low. Shows where a name is mentioned. | No reasoning, no aliases, no cross-book view. |
| **NotebookLM / "chat with your book" tools** | Medium for tech-savvy users. | No reading horizon. Users would have to upload partial books by hand. |
| **Fan wikis** | Status quo | Spoilers, ads, and patchy coverage for indie series. |

**Honest read:** as a *general consumer app*, this now competes with Amazon
on Amazon's own content, which is a losing position. As (a) a **personal /
self-hosted tool** for EPUB readers, and (b) an **author-sanctioned companion
for indie series**, it has real room. The second option also turns challenge
#2 from a liability into a pitch.

### 5.2 Authors' consent and the legal position

*Not legal advice. Verify with a lawyer before any commercial step.*

- **Personal use** of DRM-free EPUBs you own, processed locally or by an API
  that doesn't keep your data, with nothing redistributed: low risk and easy
  to defend ethically. This is roughly the same as making personal notes.
- **Removing DRM** is a separate problem. Under US law (DMCA §1201) it is
  legally risky whatever the purpose. The doc's "DRM-free only" rule is correct.
  Keep it.
- **The KU problem:** much of the indie fantasy, LitRPG, and progression
  fantasy that most needs wikis is **Kindle Unlimited exclusive**. Those books
  are DRM-protected and only available on Kindle. Readers of those series
  cannot use a BYO-EPUB tool without breaking DRM. Workarounds:
  - Authors who sell DRM-free directly (their own store, BookFunnel, Payhip,
    Kickstarter rewards).
  - Authors who give you the files directly as part of a partnership.
  - Web serials (Royal Road and similar) are where many of these series
    begin, but scraping needs author permission and must follow the site's
    terms.
- **Sharing derived knowledge** (one person's extracted wiki served to other
  users) is legally and ethically different from personal use. It moves
  toward distributing derivative works. Make it opt-in by the author.
- **The author-consent model as a feature:** "Official spoiler-safe
  companion, approved by the author." Authors can review or correct entries,
  hide planned reveals, and link to it from their newsletter. Given the
  backlash against Amazon's no-opt-out feature, this is a real point of
  difference. Your outreach plan is exactly the right next step. See
  [AUTHOR_OUTREACH.md](AUTHOR_OUTREACH.md).
- **Using a cloud model safely:** major API providers' commercial terms
  generally don't train on API inputs. Some offer zero data retention, and
  renting a GPU to run an open-weight model by the hour is another option.
  Check the current terms of whatever provider you choose, and tell authors
  plainly what is used.

### 5.3 Compute

Rough per-book estimate (verify against your hardware):

- A long fantasy novel is about 150–250k words, or about 200–330k tokens.
- An extraction pass in about 1–2k-token chunks, with prompt and context
  overhead, is roughly **0.6–1.5M input tokens and 0.1–0.3M output tokens per
  book**.
- **Local, GPU (e.g. a 24GB card or an M-series Mac, 7–14B model):** on the
  order of **1–4 hours per book**. A 20-book series is a few nights of
  unattended runs.
- **Local, CPU only:** roughly 5–10× slower. Workable for a personal
  overnight queue on one series, and painful for more.
- **Embeddings:** cheap. Small embedding models run fine on a CPU.
- **Answering questions:** a few thousand tokens per question. Fine locally.
- **API fallback:** at small or mid-tier model prices, extraction is roughly
  single-digit dollars per book. Check current pricing before relying on this.

Takeaways:
1. Ingestion is **batch, resumable, and one-time per book**. Design for that:
   a job queue, checkpointing, and idempotent steps.
2. Speed doesn't matter much. **Extraction quality from small local models**
   is the real risk. The POC should measure it against a larger model on the
   same chapters.
3. The baseline (search + summaries) needs only about one summary call per
   chapter, about 10× cheaper than full extraction. Another reason to build
   it first.

### 5.4 Reading position

Options, from most to least practical:

| Method | Precision | Effort | Notes |
|---|---|---|---|
| **Chapter picker** | Chapter | Trivial | The default. Conservative rounding (§3.4). The chapter title is always visible in the reader. |
| **Share / paste a sentence** | Passage | Low | Fuzzy-match the text to a passage. On iOS, an **Apple Shortcut** on the share sheet can POST the selected text to your server. On Android, a PWA can register as a **Web Share Target**. One tap from Kindle or Apple Books. |
| **Screenshot → OCR** | Passage | Low–medium | Share one screenshot on demand (not continuous screen reading). OCR it on the server (Tesseract or a vision model), then fuzzy-match. Works even where copying text is blocked. |
| **Percent / Kindle location** | Approximate | Low | Can be mapped to EPUB position, but varies by edition. Use only as a hint. |
| **KOReader sync** | Exact | Medium | KOReader (open source; e-ink and Android) has an open progress-sync protocol (kosync). Run a compatible sync endpoint and position updates automatically. |
| **Built-in reader** (foliate-js / epub.js / Readium) | Exact | Medium–high | The app reads the book itself, so position is exact and sync is free. It does mean asking users to switch readers. |
| **Highlight sync** (e.g. a highlight-aggregator API) | Passage | Medium | Highlight a line, and it syncs. This adds a third-party dependency. |

**Recommendation:** chapter picker plus share/paste for the POC and MVP. Add
KOReader sync or a built-in reader later, if friends want it.

---

## 6. Technical recommendations

- **Language:** Python for the pipeline. EPUB parsing, NLP, and ML tooling all
  live there.
- **LLM interface:** code against an **OpenAI-compatible chat endpoint**.
  Ollama, llama.cpp server, LM Studio, vLLM, and most cloud gateways speak it.
  Add a separate adapter for any provider that doesn't. Swapping provider
  becomes a config change. Use **structured output (JSON schema)** for
  extraction.
- **Storage:** Postgres + pgvector is fine, and Docker makes it easy.
  **SQLite + sqlite-vec + FTS5** is even simpler for a single-user POC, and
  the database is one file you can hand to a friend. Pick one. Keep the
  schema portable. Either is fine; just don't build both.
- **Positions:** one monotonic integer `pos` across the whole series (book
  order × chapter × passage sequence). Every horizon comparison is then a
  single integer comparison.
- **Pipeline runs:** every derived row records the `extractor_run_id` (model,
  prompt version). Re-run, compare, and roll back.
- **Copyrighted text never goes into git.** The library directory is
  gitignored. Develop and run CI against **public-domain** books.

### Public-domain test corpus (shareable and committable)

These books are good stress tests:
- ***The Count of Monte Cristo*** (Dumas): the best alias/reveal test there
  is. Dantès / the Count / Abbé Busoni / Lord Wilmore / Sinbad the Sailor, each
  revealed at a different point.
- ***Les Misérables***: a large cast and identity reveals (Valjean / Madeleine
  / Fauchelevent).
- **Barsoom series** (Burroughs, 11 books) or the **Oz series** (Baum, 14
  books): continuity across many books in a series with invented worlds.
- **The d'Artagnan Romances** (Dumas): continuity across books, characters who
  age, and political factions.

Standard Ebooks publishes clean, well-structured EPUBs of many of these.

---

## 7. Commercial viability: an honest view

| Path | Viability | Notes |
|---|---|---|
| Personal / friends tool | **High** | Worth doing for its own sake. Little legal exposure. |
| Open-source self-hosted | Medium | Readers who know Calibre and KOReader are a real, vocal niche. Builds reputation, not revenue. |
| Consumer SaaS, BYO books | **Low** | Competes with Amazon, carries per-user compute cost, and has ethics and legal friction. |
| **Author-sanctioned companions** (B2B2C) | **Medium; the one to test** | Authors pay, or share revenue, or it's free in exchange for promotion. Gives them reader engagement and a professional "wiki" without the upkeep. Validate in author conversations before building anything for it. |

You don't need to decide now. Build the personal tool. If the author-sanctioned path holds up in outreach, keep it in mind as you build: author review and correction, and opt-in publishing.
