-- ============================================================================
-- Check Replication Origin Usage
-- ============================================================================
-- This script helps you identify which processes are using replication origins
-- and understand the current replication state.

-- 1. List all replication origins
-- ============================================================================
-- Note: roremote_lsn and rolocal_lsn columns don't exist in pg_replication_origin view
-- Use pg_replication_origin_status for LSN information
SELECT 
    roident AS origin_id,
    roname AS origin_name
FROM pg_replication_origin
ORDER BY roident;

-- To get LSN information, use:
SELECT 
    local_id AS origin_id,
    external_id AS origin_name,
    remote_lsn,
    local_lsn
FROM pg_replication_origin_status
ORDER BY local_id;

-- 2. Check active replication origin sessions
-- ============================================================================
-- This shows which backend processes have active replication origin sessions
SELECT 
    pid AS process_id,
    usename AS username,
    application_name,
    client_addr,
    state,
    query_start,
    state_change,
    query
FROM pg_stat_activity
WHERE backend_type = 'logical replication worker'
   OR query LIKE '%pg_replication_origin%'
   OR application_name LIKE '%subscription%';

-- 3. Check subscription workers (these use replication origins)
-- ============================================================================
SELECT 
    s.subname AS subscription_name,
    s.subenabled AS enabled,
    s.subslotname AS slot_name,
    sa.pid AS worker_pid,
    sa.state AS worker_state,
    sa.query_start
FROM pg_subscription s
LEFT JOIN pg_stat_activity sa 
    ON sa.application_name LIKE '%' || s.subname || '%'
ORDER BY s.subname;

-- 4. Detailed view: Match origins to subscriptions
-- ============================================================================
SELECT 
    ro.roident AS origin_id,
    ro.roname AS origin_name,
    s.subname AS subscription_name,
    s.subenabled AS subscription_enabled,
    sa.pid AS active_worker_pid,
    sa.state AS worker_state,
    ros.remote_lsn,
    ros.local_lsn
FROM pg_replication_origin ro
LEFT JOIN pg_replication_origin_status ros 
    ON ro.roident = ros.local_id
LEFT JOIN pg_subscription s 
    ON ro.roname LIKE 'pg_%' 
    AND s.oid::text = SUBSTRING(ro.roname FROM 'pg_(\d+)')
LEFT JOIN pg_stat_activity sa 
    ON sa.application_name LIKE '%' || s.subname || '%'
ORDER BY ro.roident;

-- 5. Check for locks on replication origins
-- ============================================================================
SELECT 
    locktype,
    database,
    relation,
    pid,
    mode,
    granted
FROM pg_locks
WHERE locktype = 'object' 
   OR pid IN (
       SELECT pid 
       FROM pg_stat_activity 
       WHERE backend_type = 'logical replication worker'
   );

-- 6. Find the subscription associated with each origin
-- ============================================================================
-- The origin name format is 'pg_<subscription_oid>'
-- This query decodes that relationship
SELECT 
    ro.roident AS origin_id,
    ro.roname AS origin_name,
    s.oid AS subscription_oid,
    s.subname AS subscription_name,
    s.subenabled AS is_enabled,
    CASE 
        WHEN s.subenabled THEN 'Active (enabled)'
        ELSE 'Inactive (disabled)'
    END AS status
FROM pg_replication_origin ro
LEFT JOIN pg_subscription s 
    ON ro.roname = 'pg_' || s.oid::text
ORDER BY ro.roident;

-- ============================================================================
-- INTERPRETATION GUIDE
-- ============================================================================
-- 
-- If origin is "already active" error occurs:
-- 1. Check query #3 - Look for worker_pid with state 'active' or 'idle in transaction'
-- 2. Check query #6 - See if origin is linked to an enabled subscription
-- 3. If subscription is enabled, the origin is being used by subscription worker
-- 
-- To resolve "already active" error:
-- - Option 1: Use session-based approach (already implemented in the script)
-- - Option 2: Temporarily disable subscription: ALTER SUBSCRIPTION <name> DISABLE;
-- - Option 3: Drop and recreate subscription
-- 
-- ============================================================================
