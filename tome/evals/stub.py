"""A small hand-written stub pack for exercising the eval harness end to end.

It mimics *The Count of Monte Cristo*: one book with the real 117-chapter
grid, so the public eval cases (anchored to real chapter numbers) resolve
sensibly. Passage text is short synthetic paraphrase, not the novel.

Crucially it contains derived rows that are spoilers for earlier horizons
(Busoni is the Count, Andrea is Benedetto, Morcerf's suicide...). A broken
horizon layer would leak them, which is exactly what the evals look for.
A few observations carry bad quotes so the quote-check stats are non-trivial.
"""

from __future__ import annotations

from pathlib import Path

from tome.pack_writer import BookText, ChapterText, PackWriter

STUB_PACK_ID = "monte-cristo"
CHAPTERS = 117

TITLES = {
    1: "Marseilles—The Arrival",
    3: "The Catalans",
    4: "Conspiracy",
    8: "The Château d’If",
    15: "Number 34 and Number 27",
    18: "The Treasure",
    20: "The Cemetery of the Château d’If",
    25: "The Unknown",
    26: "The Pont du Gard Inn",
    29: "The House of Morrel & Son",
    30: "The Fifth of September",
    31: "Italy: Sinbad the Sailor",
    33: "Roman Bandits",
    35: "La Mazzolata",
    43: "The House at Auteuil",
    44: "The Vendetta",
    45: "The Rain of Blood",
    55: "Major Cavalcanti",
    64: "The Beggar",
    66: "Matrimonial Projects",
    69: "The Inquiry",
    77: "Haydée",
    82: "The Burglary",
    92: "The Suicide",
    117: "The Fifth of October",
}

PASSAGES = {
    1: "Edmond Dantès, the young first mate of the Pharaon, brings the ship into Marseilles "
    "after the death of Captain Leclère. The owner, M. Morrel, means to make him captain.",
    3: "Mercédès, a beautiful Catalan girl, is betrothed to Edmond Dantès. Her cousin Fernand "
    "Mondego loves her and is bitterly jealous of the young sailor.",
    4: "Danglars writes an anonymous letter denouncing Dantès as a Bonapartist agent, and "
    "Fernand carries the letter to the post.",
    8: "Dantès is taken by night to the Château d’If and thrown into a dungeon without trial.",
    15: "In the dungeon Dantès meets the Abbé Faria, prisoner Number 27, an old Italian priest "
    "who has spent years digging a tunnel.",
    18: "Faria tells Dantès of the treasure of the Spada family, hidden on the island of "
    "Monte Cristo.",
    20: "Sewn into the dead abbé’s sack, Dantès is thrown into the sea and escapes the "
    "Château d’If.",
    25: "Dantès next proceeded thither, and, under the name of Lord Wilmore, purchased the "
    "small dwelling in the Allées de Meilhan.",
    26: "A priest on horseback arrives at the Pont du Gard inn kept by Caderousse and asks "
    "him about Edmond Dantès.",
    29: "The house of Morrel is saved from ruin by an unknown benefactor; the note left with "
    "the purse is signed Sinbad the Sailor.",
    30: "A new Pharaon sails into Marseilles. A bearded man watching from behind the "
    "sentry-box bids farewell to kindness and sails away on a yacht.",
    31: "On the island of Monte Cristo, Franz d’Épinay dines with a mysterious host who says "
    "he is generally called Sinbad the Sailor.",
    33: "At Rome, the innkeeper Pastrini speaks of his neighbour, the Count of Monte Cristo.",
    35: "Franz recognizes the Count of Monte Cristo as his host from the island, the man he "
    "knew as Sinbad the Sailor.",
    43: "Bertuccio, the count’s steward, says that the Abbé Busoni recommended him to the count.",
    44: "Bertuccio tells how he rescued a newborn child at Auteuil and named him Benedetto.",
    45: "Haydée, a young Greek woman of great beauty, lives in the count’s house.",
    55: "Andrea Cavalcanti arrives in Paris, presented as the son of Major Cavalcanti.",
    64: "Caderousse stops Andrea Cavalcanti in the street and calls him Benedetto, his old "
    "friend from the galleys.",
    66: "The count tells Danglars that his friend the Abbé Busoni has just arrived in Paris.",
    69: "Lord Wilmore pulled off his light hair, his red whiskers and his false jaw, to resume "
    "the black hair and pearly teeth of the Count of Monte Cristo.",
    77: "Haydée tells Albert that she is the daughter of Ali Tepelini, Pasha of Yanina, sold "
    "into slavery after her father was betrayed.",
    82: "“The Abbé Busoni!” exclaimed Caderousse. “Yes, undoubtedly, the Abbé Busoni "
    "himself,” replied Monte Cristo.",
    92: "The count reveals his true name to Morcerf, who flees crying “Edmond Dantès!” and "
    "later shoots himself.",
    117: "The Count of Monte Cristo, who was Edmond Dantès, sails away with Haydée and leaves a "
    "letter that ends: wait and hope.",
}

# entity key -> (kind, first chapter, [(alias, chapter established)])
ENTITIES = {
    "dantes": ("person", 1, [("Edmond Dantès", 1), ("Dantès", 1), ("Edmond", 1)]),
    "mercedes": ("person", 3, [("Mercédès", 3)]),
    "fernand": (
        "person",
        3,
        [("Fernand Mondego", 3), ("Fernand", 3), ("Count de Morcerf", 44), ("Morcerf", 44)],
    ),
    "danglars": ("person", 4, [("Danglars", 4)]),
    "faria": ("person", 15, [("Abbé Faria", 15), ("Faria", 15)]),
    "wilmore": ("person", 25, [("Lord Wilmore", 25), ("Wilmore", 25)]),
    "caderousse": ("person", 26, [("Caderousse", 26)]),
    "sinbad": ("person", 29, [("Sinbad the Sailor", 29), ("Sinbad", 29)]),
    "count": (
        "person",
        33,
        [("Count of Monte Cristo", 33), ("Monte Cristo", 33), ("the count", 33)],
    ),
    "busoni": ("person", 43, [("Abbé Busoni", 43), ("Busoni", 43)]),
    "benedetto": ("person", 44, [("Benedetto", 44)]),
    "haydee": ("person", 45, [("Haydée", 45)]),
    "andrea": ("person", 55, [("Andrea Cavalcanti", 55), ("Andrea", 55)]),
}

# (entity, same_as, chapter established)
IDENTITIES = [
    ("wilmore", "dantes", 25),
    ("sinbad", "count", 35),
    ("andrea", "benedetto", 64),
    ("wilmore", "count", 69),
    ("busoni", "count", 82),
    ("count", "dantes", 92),
]

# (entity, checkpoint chapter, display name, text)
PROFILES = [
    ("dantes", 1, "Edmond Dantès", "Edmond Dantès is the young first mate of the Pharaon."),
    (
        "dantes",
        8,
        "Edmond Dantès",
        "Edmond Dantès, first mate of the Pharaon and betrothed to "
        "Mercédès, was arrested on a denunciation and imprisoned in the Château d’If.",
    ),
    (
        "dantes",
        20,
        "Edmond Dantès",
        "Edmond Dantès was imprisoned in the Château d’If, taught "
        "by the Abbé Faria, and escaped in Faria’s burial sack.",
    ),
    ("mercedes", 3, "Mercédès", "Mercédès is a Catalan girl betrothed to Edmond Dantès."),
    (
        "fernand",
        3,
        "Fernand Mondego",
        "Fernand Mondego is a Catalan, cousin of Mercédès, who loves her.",
    ),
    (
        "fernand",
        92,
        "Count de Morcerf",
        "The Count de Morcerf, once Fernand Mondego, killed "
        "himself after his betrayal of Ali Pasha was exposed.",
    ),
    (
        "danglars",
        4,
        "Danglars",
        "Danglars is the jealous supercargo who wrote the anonymous letter denouncing Dantès.",
    ),
    (
        "faria",
        15,
        "Abbé Faria",
        "The Abbé Faria is an Italian priest held in the Château d’If as prisoner Number 27.",
    ),
    (
        "faria",
        18,
        "Abbé Faria",
        "The Abbé Faria, prisoner Number 27, told Dantès of the Spada "
        "treasure on the island of Monte Cristo.",
    ),
    (
        "wilmore",
        25,
        "Lord Wilmore",
        "Lord Wilmore is the name Edmond Dantès uses on his passport after his escape.",
    ),
    (
        "wilmore",
        69,
        "Lord Wilmore",
        "Lord Wilmore claims to be the count’s enemy, but he is "
        "the Count of Monte Cristo in disguise.",
    ),
    (
        "sinbad",
        29,
        "Sinbad the Sailor",
        "Sinbad the Sailor is the signature on the note that saved the house of Morrel.",
    ),
    (
        "sinbad",
        31,
        "Sinbad the Sailor",
        "Sinbad the Sailor is the name used by Franz’s "
        "mysterious host on the island of Monte Cristo.",
    ),
    (
        "count",
        33,
        "Count of Monte Cristo",
        "The Count of Monte Cristo is a rich foreign nobleman staying in Rome.",
    ),
    (
        "count",
        92,
        "Count of Monte Cristo",
        "The Count of Monte Cristo revealed to Morcerf that he is Edmond Dantès.",
    ),
    (
        "busoni",
        43,
        "Abbé Busoni",
        "The Abbé Busoni is a priest who heard Bertuccio’s "
        "confession and recommended him to the count.",
    ),
    ("busoni", 66, "Abbé Busoni", "The Abbé Busoni is a priest the count calls his friend."),
    ("busoni", 82, "Abbé Busoni", "The Abbé Busoni is the Count of Monte Cristo in disguise."),
    ("benedetto", 44, "Benedetto", "Benedetto is the child Bertuccio rescued at Auteuil."),
    ("haydee", 45, "Haydée", "Haydée is a young Greek woman living in the count’s house."),
    (
        "haydee",
        77,
        "Haydée",
        "Haydée is the daughter of Ali Tepelini, Pasha of Yanina, sold "
        "into slavery after his betrayal.",
    ),
    (
        "andrea",
        55,
        "Andrea Cavalcanti",
        "Andrea Cavalcanti is presented in Paris as the son of Major Cavalcanti.",
    ),
    (
        "andrea",
        64,
        "Andrea Cavalcanti",
        "Andrea Cavalcanti is really Benedetto, Caderousse’s old companion from the galleys.",
    ),
]

# (subject, chapter, predicate, sentence, quote, status, claimed_by)
OBSERVATIONS = [
    (
        "dantes",
        1,
        "role",
        "Dantès is first mate of the Pharaon.",
        "the young first mate of the Pharaon",
        "stated",
        None,
    ),
    (
        "mercedes",
        3,
        "betrothed_to",
        "Mercédès is betrothed to Edmond Dantès.",
        "is betrothed to Edmond Dantès",
        "stated",
        None,
    ),
    (
        "danglars",
        4,
        "wrote",
        "Danglars denounced Dantès as a Bonapartist agent.",
        "anonymous letter denouncing Dantès as a Bonapartist agent",
        "stated",
        None,
    ),
    (
        "faria",
        15,
        "prisoner_number",
        "Faria is prisoner Number 27.",
        "the Abbé Faria, prisoner Number 27",
        "stated",
        None,
    ),
    (
        "wilmore",
        25,
        "alias_of",
        "Dantès bought a house under the name Lord Wilmore.",
        "under the name of Lord Wilmore",
        "stated",
        None,
    ),
    (
        "sinbad",
        29,
        "saved",
        "A note signed Sinbad the Sailor came with the purse that saved the Morrels.",
        "is signed Sinbad the Sailor",
        "stated",
        None,
    ),
    (
        "busoni",
        66,
        "friend_of",
        "The count says the Abbé Busoni is his friend.",
        "his friend the Abbé Busoni has just arrived",
        "claimed",
        "count",
    ),
    (
        "andrea",
        64,
        "called",
        "Caderousse calls Andrea Cavalcanti “Benedetto”.",
        "calls him Benedetto, his old friend from the galleys",
        "stated",
        None,
    ),
    (
        "haydee",
        77,
        "daughter_of",
        "Haydée is the daughter of Ali Tepelini.",
        "she is the daughter of Ali Tepelini",
        "stated",
        None,
    ),
    (
        "busoni",
        82,
        "is",
        "The Abbé Busoni is the count in disguise.",
        "the Abbé Busoni himself,” replied Monte Cristo",
        "stated",
        None,
    ),
    ("fernand", 92, "fate", "Morcerf shoots himself.", "later shoots himself", "stated", None),
    # Two candidates whose quotes are not in the text: the quote check drops them.
    (
        "count",
        33,
        "is",
        "The count is Edmond Dantès.",
        "the Count, who is really Edmond Dantès",
        "stated",
        None,
    ),
    (
        "haydee",
        45,
        "daughter_of",
        "Haydée is Ali Pasha's daughter.",
        "Haydée, daughter of Ali Pasha",
        "stated",
        None,
    ),
]

SUMMARIES = {n: text for n, text in PASSAGES.items()}

ROLLUPS = [
    (
        30,
        "Edmond Dantès was betrayed by Danglars and Fernand, imprisoned in the Château d’If, "
        "escaped with the Abbé Faria’s secret, and has quietly rewarded the Morrels as Sinbad "
        "the Sailor.",
    ),
    (
        69,
        "The Count of Monte Cristo has settled in Paris among Danglars, Morcerf and "
        "Villefort; Lord Wilmore has been shown to be the count in disguise.",
    ),
    (
        117,
        "The Count of Monte Cristo, Edmond Dantès, has taken his revenge and sails away "
        "with Haydée.",
    ),
]

# (chapter, question, answer, cited chapters)
ANTICIPATED = [
    (
        8,
        "Why was Dantès arrested?",
        "Danglars wrote an anonymous letter denouncing him as a "
        "Bonapartist agent, and Fernand posted it.",
        [4],
    ),
    (
        30,
        "Who saved the house of Morrel?",
        "An unknown benefactor whose note was signed Sinbad the Sailor.",
        [29],
    ),
    (82, "Who is the Abbé Busoni really?", "The Count of Monte Cristo in disguise.", [82]),
]


def build_stub_pack(path: str | Path, *, overwrite: bool = True) -> Path:
    path = Path(path)
    w = PackWriter(
        path,
        pack_id=STUB_PACK_ID,
        series_title="The Count of Monte Cristo (stub)",
        overwrite=overwrite,
    )
    chapters = []
    for n in range(1, CHAPTERS + 1):
        text = PASSAGES.get(n, f"Stub placeholder passage for chapter {n}.")
        chapters.append(ChapterText(f"{n}: {TITLES.get(n, f'Chapter {n}')}", [text]))
    w.add_book(1, BookText("The Count of Monte Cristo", chapters, "stub", None))

    def ch_pos(n: int) -> int:
        return w.chapter(1, n)["end_pos"]

    def ch_passage(n: int) -> int:
        return w.passage_at(ch_pos(n))["passage_id"]

    run = w.start_run(
        "stub", llm_provider="hand-written", llm_model="none", prompt_version="stub-v0"
    )
    ids: dict[str, int] = {}
    for key, (kind, first_ch, aliases) in ENTITIES.items():
        ids[key] = w.add_entity(
            kind=kind, first_pos=ch_pos(first_ch), run_id=run, attributes={"stub_key": key}
        )
        for surface, ch in aliases:
            w.add_alias(
                entity_id=ids[key],
                surface_form=surface,
                established_at=ch_pos(ch),
                evidence_passage_id=ch_passage(ch),
                run_id=run,
            )
    for a, b, ch in IDENTITIES:
        w.add_identity(
            entity_id=ids[a],
            same_as_entity_id=ids[b],
            established_at=ch_pos(ch),
            evidence_passage_id=ch_passage(ch),
            run_id=run,
        )
    prev: dict[str, int] = {}
    for key, ch, name, text in PROFILES:
        prev[key] = w.add_profile(
            entity_id=ids[key],
            checkpoint_pos=ch_pos(ch),
            display_name=name,
            profile_text=text,
            max_source_pos=ch_pos(ch),
            run_id=run,
            prev_profile_id=prev.get(key),
        )
    for subj, ch, pred, sentence, quote, status, claimed_by in OBSERVATIONS:
        w.add_observation(
            sentence=sentence,
            subject_entity_id=ids[subj],
            predicate=pred,
            evidence_passage_id=ch_passage(ch),
            quote=quote,
            status=status,
            claimed_by_entity_id=ids[claimed_by] if claimed_by else None,
            run_id=run,
        )
    w.add_relationship(
        source_entity_id=ids["mercedes"],
        target_entity_id=ids["dantes"],
        rel_type="betrothed",
        description="Mercédès is betrothed to Dantès.",
        pos=ch_pos(3),
        evidence_passage_id=ch_passage(3),
        run_id=run,
    )
    w.add_relationship(
        source_entity_id=ids["faria"],
        target_entity_id=ids["dantes"],
        rel_type="mentor",
        description="Faria teaches Dantès in prison.",
        pos=ch_pos(15),
        evidence_passage_id=ch_passage(15),
        run_id=run,
    )
    for n, text in SUMMARIES.items():
        w.add_chapter_summary(
            chapter_id=w.chapter(1, n)["chapter_id"], summary_text=text, run_id=run
        )
    for ch, text in ROLLUPS:
        w.add_rollup(
            kind="story_so_far",
            text=text,
            max_source_pos=ch_pos(ch),
            run_id=run,
            book_id=1,
            through_chapter_id=w.chapter(1, ch)["chapter_id"],
        )
    for ch, q, a, cited in ANTICIPATED:
        w.add_anticipated_qa(
            chapter_id=w.chapter(1, ch)["chapter_id"],
            question=q,
            answer=a,
            evidence_passage_ids=[ch_passage(c) for c in cited],
            max_source_pos=ch_pos(ch),
            run_id=run,
        )
    w.finish_run(run)
    w.finalize(llm_model="none (stub)")
    w.close()
    return path
