-- Identity reveals must be stated by the text (DECISIONS.md §9).
--
-- An entity_identities row (Busoni is the Count, Scabbers is Pettigrew) is
-- the most dangerous thing a pack can hold, so it gets the same mechanical
-- check as observations: a verbatim quote from the evidence passage, and that
-- passage is the reveal point itself (its pos = established_at). An LLM's
-- inference that two characters "must be" the same person cannot be stored.

ALTER TABLE entity_identities ADD COLUMN quote_span TEXT;
ALTER TABLE entity_identities ADD COLUMN quote_start INTEGER;
ALTER TABLE entity_identities ADD COLUMN quote_end INTEGER;

CREATE TRIGGER entity_identities_stated_insert
BEFORE INSERT ON entity_identities
WHEN NEW.quote_span IS NULL OR NOT EXISTS (
    SELECT 1 FROM passages p
    WHERE p.passage_id = NEW.evidence_passage_id
      AND p.pos = NEW.established_at
      AND substr(p.text, NEW.quote_start + 1, NEW.quote_end - NEW.quote_start) = NEW.quote_span
)
BEGIN
    SELECT RAISE(ABORT, 'stated-reveal: identity needs a verbatim quote from the passage at established_at');
END;

CREATE TRIGGER entity_identities_stated_update
BEFORE UPDATE ON entity_identities
WHEN NEW.quote_span IS NULL OR NOT EXISTS (
    SELECT 1 FROM passages p
    WHERE p.passage_id = NEW.evidence_passage_id
      AND p.pos = NEW.established_at
      AND substr(p.text, NEW.quote_start + 1, NEW.quote_end - NEW.quote_start) = NEW.quote_span
)
BEGIN
    SELECT RAISE(ABORT, 'stated-reveal: identity needs a verbatim quote from the passage at established_at');
END;
