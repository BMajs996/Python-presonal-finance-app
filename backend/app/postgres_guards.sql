CREATE FUNCTION finance_writer_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(618370201);
    RETURN NULL;
END $$;

CREATE FUNCTION finance_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (TG_TABLE_NAME='transactions' AND EXISTS (
        SELECT 1 FROM reconciliation_entries WHERE transaction_id=OLD.id
    )) OR (TG_TABLE_NAME='transfers' AND EXISTS (
        SELECT 1 FROM reconciliation_entries WHERE transfer_id=OLD.id
    )) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Reconciliation: entry locked; uncheck it in its draft before editing';
    END IF;
    IF TG_TABLE_NAME='transactions' AND TG_OP='DELETE' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Transactions must be soft deleted';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER finance_transaction_guard BEFORE UPDATE OR DELETE ON transactions
    FOR EACH ROW EXECUTE FUNCTION finance_source_guard();
CREATE TRIGGER finance_transfer_guard BEFORE UPDATE OR DELETE ON transfers
    FOR EACH ROW EXECUTE FUNCTION finance_source_guard();

CREATE FUNCTION finance_audit_write() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE before_json JSONB; after_json JSONB; event_action TEXT;
BEGIN
    IF TG_OP='UPDATE' AND OLD IS NOT DISTINCT FROM NEW THEN RETURN NEW; END IF;
    after_json := (to_jsonb(NEW) - 'amount') || jsonb_build_object(
        'currency', (SELECT currency FROM accounts WHERE id=NEW.account_id),
        'account_name', (SELECT name FROM accounts WHERE id=NEW.account_id));
    IF TG_OP='INSERT' THEN
        event_action := 'created';
    ELSE
        before_json := (to_jsonb(OLD) - 'amount') || jsonb_build_object(
            'currency', (SELECT currency FROM accounts WHERE id=OLD.account_id),
            'account_name', (SELECT name FROM accounts WHERE id=OLD.account_id));
        event_action := CASE
            WHEN OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN 'deleted'
            WHEN OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL THEN 'restored'
            ELSE 'updated' END;
    END IF;
    INSERT INTO transaction_audit(transaction_id,action,before_state,after_state)
        VALUES(NEW.id,event_action,before_json::text,after_json::text);
    RETURN NEW;
END $$;
CREATE TRIGGER finance_audit AFTER INSERT OR UPDATE ON transactions
    FOR EACH ROW EXECUTE FUNCTION finance_audit_write();
CREATE FUNCTION finance_audit_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Transaction audit history is append-only';
END $$;
CREATE TRIGGER finance_audit_immutable BEFORE UPDATE OR DELETE ON transaction_audit
    FOR EACH ROW EXECUTE FUNCTION finance_audit_guard();

CREATE FUNCTION finance_statement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cleared NUMERIC;
BEGIN
    IF TG_OP='INSERT' THEN
        IF NEW.status<>'draft' OR NEW.completed_at IS NOT NULL THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Reconciliation: statements must begin as drafts';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status='completed' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Reconciliation: completed statements are read-only';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    IF (NEW.account_id,NEW.closing_date,NEW.opening_balance_cents,NEW.closing_balance_cents)
       IS DISTINCT FROM (OLD.account_id,OLD.closing_date,OLD.opening_balance_cents,OLD.closing_balance_cents) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Reconciliation: cancel the draft to change statement details';
    END IF;
    IF NEW.status='completed' THEN
        SELECT COALESCE(SUM(l.amount_cents),0) INTO cleared
        FROM reconciliation_entries e JOIN reconciliation_ledger l ON l.account_id=e.account_id
          AND ((l.kind='transaction' AND l.entry_id=e.transaction_id)
            OR (l.kind='transfer' AND l.entry_id=e.transfer_id))
        WHERE e.reconciliation_id=OLD.id;
        IF NEW.completed_at IS NULL OR NEW.closing_balance_cents<>NEW.opening_balance_cents+cleared THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Reconciliation: statement difference must be zero';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER finance_statement_guard BEFORE INSERT OR UPDATE OR DELETE ON reconciliations
    FOR EACH ROW EXECUTE FUNCTION finance_statement_guard();

CREATE FUNCTION finance_cleared_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Reconciliation: cleared entries cannot be reassigned';
    ELSIF TG_OP='DELETE' THEN
        IF EXISTS (SELECT 1 FROM reconciliations WHERE id=OLD.reconciliation_id AND status='completed') THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Reconciliation: completed statements are read-only';
        END IF;
        RETURN OLD;
    ELSIF NOT EXISTS (
        SELECT 1 FROM reconciliations r JOIN reconciliation_ledger l ON l.account_id=r.account_id
        WHERE r.id=NEW.reconciliation_id AND r.account_id=NEW.account_id AND r.status='draft'
          AND l.date<=r.closing_date
          AND ((l.kind='transaction' AND l.entry_id=NEW.transaction_id)
            OR (l.kind='transfer' AND l.entry_id=NEW.transfer_id))
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Reconciliation: entry is not eligible';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER finance_cleared_guard BEFORE INSERT OR UPDATE OR DELETE ON reconciliation_entries
    FOR EACH ROW EXECUTE FUNCTION finance_cleared_guard();

CREATE FUNCTION finance_account_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM reconciliations WHERE account_id=OLD.id)
       AND (NEW.opening_balance,NEW.opening_balance_cents,NEW.currency)
           IS DISTINCT FROM (OLD.opening_balance,OLD.opening_balance_cents,OLD.currency) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Reconciliation: account opening balance and currency are locked';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER finance_account_guard BEFORE UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION finance_account_guard();
