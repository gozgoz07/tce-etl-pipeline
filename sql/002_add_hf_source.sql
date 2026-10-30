-- Migration 002: Add 'hf' (Hugging Face) to items source CHECK constraint
DO $$
DECLARE
    constraint_rec RECORD;
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'items') THEN
        FOR constraint_rec IN
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'items'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%source%'
        LOOP
            EXECUTE 'ALTER TABLE items DROP CONSTRAINT ' || quote_ident(constraint_rec.conname);
        END LOOP;

        ALTER TABLE items ADD CONSTRAINT items_source_check CHECK (source IN ('hn', 'arxiv', 'rss', 'hf'));
    END IF;
END $$;
