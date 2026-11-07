"""Rolling chapter summaries, book recaps and "story so far" rollups.

Compile-time only (invariant 4). Chapters are processed strictly in reading
order, and each prompt holds only that chapter's text plus summaries of what
came before it (invariant 3). The writer's reading cursor rejects any row that
claims a later source position.

Summaries are written from stated facts only (DECISIONS.md §9), so the prompts
tell the model to ignore anything it remembers about the book.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

from tome.llm.client import ChatClient, LLMError
from tome.pack_writer import PackWriter
from tome.text import word_count

PROMPT_VERSION = "summaries-v3"
ROLLUP_EVERY = 5  # chapters between "story so far" checkpoints
# About 8k tokens, which leaves room for the context and the reply in the
# pod's default 16,384-token window.
CHUNK_WORDS = 6000
CHAPTER_MAX_TOKENS = 700
ROLLUP_MAX_TOKENS = 1100
CALL_ATTEMPTS = 3
RETRY_DELAY_S = 5.0

SYSTEM = """You write summaries for a spoiler-safe reading companion. The reader has read \
only up to the point you are given.

Rules:
- Use only the text and earlier summaries in this message. You may recognise this book: \
ignore anything you remember about it, including later events, the ending and later \
revelations.
- State only what the text states. Do not guess at secrets, hidden identities, motives or \
what will happen next. If a character claims something, say that they claim it. If the text \
says a person's identity is unknown, leave it unknown.
- Call people what the text has called them so far.
- Never foreshadow, or hint that something will matter later.
- Write plain past-tense prose with no heading, preamble or closing comment. Tell the story \
itself: never mention chapters, "the text" or what it does or does not reveal."""


@dataclass
class SummaryStats:
    chapters: int = 0
    story_so_far: int = 0
    book_recaps: int = 0
    llm_calls: int = 0
    truncated: int = 0  # replies cut off by the token limit
    rollups_skipped: int = 0  # never stored: a cut-off rollup would hide recent events
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None


def chunk_passages(passages: Sequence[str], max_words: int = CHUNK_WORDS) -> list[list[str]]:
    """Group passages, in order, into chunks of at most ``max_words`` where possible.

    A single passage longer than ``max_words`` stays whole in its own chunk.
    """
    chunks: list[list[str]] = []
    size = 0
    for passage in passages:
        n = word_count(passage)
        if chunks and size + n <= max_words:
            chunks[-1].append(passage)
            size += n
        else:
            chunks.append([passage])
            size = n
    return chunks


class _Summarizer:
    def __init__(self, client: ChatClient, sleep: Callable[[float], None]):
        self.client = client
        self.sleep = sleep
        self.stats = SummaryStats()

    def _call(self, prompt: str, *, purpose: str, max_tokens: int) -> tuple[str, bool]:
        """One reply and whether the token limit cut it off, retrying transient errors."""
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
        for attempt in range(1, CALL_ATTEMPTS + 1):
            try:
                result = self.client.chat(messages, purpose=purpose, max_tokens=max_tokens)
                if not result.text.strip():
                    raise LLMError("empty reply")
                break
            except LLMError:
                if attempt == CALL_ATTEMPTS:
                    raise
                self.sleep(RETRY_DELAY_S * attempt)
        s = self.stats
        s.llm_calls += 1
        s.prompt_tokens += result.prompt_tokens
        s.completion_tokens += result.completion_tokens
        if result.cost_usd is not None:
            s.cost_usd = (s.cost_usd or 0.0) + result.cost_usd
        cut_off = result.raw["choices"][0].get("finish_reason") == "length"
        if cut_off:
            s.truncated += 1
        return result.text.strip(), cut_off

    def _complete(self, prompt: str, *, purpose: str, max_tokens: int, words: int) -> str | None:
        """A reply that finished, asking once for a shorter one. None if it never did."""
        text, cut_off = self._call(prompt, purpose=purpose, max_tokens=max_tokens)
        if not cut_off:
            return text
        shorter = f"{prompt}\n\nBe much briefer: use at most {words} words."
        text, cut_off = self._call(shorter, purpose=purpose, max_tokens=max_tokens)
        return None if cut_off else text

    def chapter(
        self,
        label: str,
        story: str,
        recent: Sequence[str],
        passages: Sequence[str],
        chunk_words: int,
    ) -> str:
        context = []
        if story:
            context.append(f"STORY SO FAR:\n{story}")
        if recent:
            context.append("CHAPTERS SINCE THEN, IN ORDER:\n" + "\n\n".join(recent))
        draft = ""
        for chunk in chunk_passages(passages, chunk_words):
            parts = list(context)
            if draft:
                parts.append(f"SUMMARY OF THIS CHAPTER SO FAR:\n{draft}")
            parts.append(f"TEXT OF {label}:\n" + "\n\n".join(chunk))
            task = (
                "Rewrite the summary of this chapter so it also covers the text above"
                if draft
                else "Summarize this chapter"
            )
            parts.append(
                f"{task} in 100 to 250 words. Cover the events and who was involved, and "
                "anything new the text states about a character or place."
            )
            prompt = "\n\n".join(parts)
            reply = self._complete(
                prompt, purpose="chapter_summary", max_tokens=CHAPTER_MAX_TOKENS, words=120
            )
            if reply is None:
                raise LLMError(f"summary of {label} was cut off twice")
            draft = reply
        return draft

    def story_so_far(
        self, label: str, earlier_books: Sequence[str], book_summaries: Sequence[str]
    ) -> str | None:
        """Rebuilt from every chapter of this book: rewriting the last rollup loses the start."""
        parts = []
        if earlier_books:
            parts.append("RECAPS OF EARLIER BOOKS, IN ORDER:\n" + "\n\n".join(earlier_books))
        parts.append("CHAPTERS OF THIS BOOK SO FAR, IN ORDER:\n" + "\n\n".join(book_summaries))
        parts.append(
            f"Write the story so far, through {label}, in at most 400 words. Cover the whole "
            "story in order, from its very beginning to the end of the last chapter, giving "
            "each major event a sentence or less. Keep what a returning reader needs: main "
            "events, who is who, and what is unresolved at this point."
        )
        return self._complete(
            "\n\n".join(parts), purpose="story_so_far", max_tokens=ROLLUP_MAX_TOKENS, words=200
        )

    def book_recap(self, title: str, summaries: Sequence[str]) -> str | None:
        prompt = (
            f"CHAPTER SUMMARIES OF {title}, IN ORDER:\n" + "\n\n".join(summaries) + "\n\n"
            "Write a recap of this book in at most 400 words, for a reader starting the next one."
        )
        return self._complete(prompt, purpose="book_recap", max_tokens=ROLLUP_MAX_TOKENS, words=200)


def summarize_pack(
    w: PackWriter,
    client: ChatClient,
    *,
    rollup_every: int = ROLLUP_EVERY,
    max_chapters: int | None = None,
    chunk_words: int = CHUNK_WORDS,
    log: Callable[[str], None] = lambda _msg: None,
    sleep: Callable[[float], None] = time.sleep,
) -> SummaryStats:
    """Write summaries and rollups for the pack's books, in reading order.

    ``max_chapters`` stops early, for cheap trial runs. It always stops after a
    "story so far" checkpoint, so a trial exercises the rollup too.
    """
    if rollup_every < 1:
        raise ValueError("rollup_every must be at least 1")
    s = _Summarizer(client, sleep)
    run = w.start_run(
        "summaries",
        llm_provider=client.provider.name,
        llm_model=client.model,
        prompt_version=PROMPT_VERSION,
        params={
            "rollup_every": rollup_every,
            "max_chapters": max_chapters,
            "chunk_words": chunk_words,
        },
    )
    story = ""
    recent: list[str] = []
    earlier_books: list[str] = []
    done = 0
    books = w.conn.execute("SELECT * FROM books ORDER BY number").fetchall()
    for book in books:
        chapters = w.conn.execute(
            "SELECT * FROM chapters WHERE book_id=? ORDER BY start_pos", (book["book_id"],)
        ).fetchall()
        book_summaries: list[str] = []
        for chapter in chapters:
            done += 1
            stopping = max_chapters is not None and done >= max_chapters
            w.cursor = chapter["end_pos"]
            label = f"BOOK {book['number']}, CHAPTER {chapter['number']} ({chapter['title']})"
            passages = [
                r["text"]
                for r in w.conn.execute(
                    "SELECT text FROM passages WHERE chapter_id=? ORDER BY pos",
                    (chapter["chapter_id"],),
                )
            ]
            summary = s.chapter(label, story, recent, passages, chunk_words)
            w.add_chapter_summary(
                chapter_id=chapter["chapter_id"], summary_text=summary, run_id=run
            )
            s.stats.chapters += 1
            log(f"b{book['number']} ch{chapter['number']}: summarized")
            recent.append(f"{label}:\n{summary}")
            book_summaries.append(f"Chapter {chapter['number']}: {summary}")

            book_done = chapter["end_pos"] == book["end_pos"]
            if book_done or stopping or len(recent) >= rollup_every:
                new_story = s.story_so_far(label, earlier_books, book_summaries)
                if new_story is None:
                    # Nothing is lost: a recap covers chapters after the last rollup one by one.
                    s.stats.rollups_skipped += 1
                else:
                    story = new_story
                    w.add_rollup(
                        kind="story_so_far",
                        text=story,
                        max_source_pos=chapter["end_pos"],
                        run_id=run,
                        book_id=book["book_id"],
                        through_chapter_id=chapter["chapter_id"],
                    )
                    s.stats.story_so_far += 1
                    recent = []
            if book_done:
                recap = s.book_recap(book["title"], book_summaries)
                if recap is None:
                    s.stats.rollups_skipped += 1
                else:
                    w.add_rollup(
                        kind="book",
                        text=recap,
                        max_source_pos=chapter["end_pos"],
                        run_id=run,
                        book_id=book["book_id"],
                        through_chapter_id=chapter["chapter_id"],
                    )
                    s.stats.book_recaps += 1
                earlier_books.append(recap or story)
            if stopping:
                break
        else:
            continue
        break
    w.cursor = None
    st = s.stats
    w.finish_run(
        run,
        stats=asdict(st),
        prompt_tokens=st.prompt_tokens,
        completion_tokens=st.completion_tokens,
        cost_usd=st.cost_usd,
    )
    return st
