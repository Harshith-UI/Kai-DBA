
# Oracle Tablespace Extension — Add Datafile or Resize Existing
## Overview

This document covers the procedure for extending an Oracle Database tablespace when
available free space falls below the defined alert threshold (20%) or when an
`ORA-01653`/`ORA-01654` error is encountered during application operations. It exists to
provide a safe, repeatable, and auditable method for DBA team members to restore normal
database operations with minimal disruption.

**Purpose:** Extend an Oracle tablespace by adding a new datafile or by resizing an
existing datafile so that the database can continue normal read/write operations.

**Background:** Oracle Database allocates storage in units called tablespaces — logical
containers composed of one or more physical datafiles. When a tablespace exhausts its
allocated space, any DML (Data Manipulation Language) operations that require space will
fail with an error. Standardized procedures are critical to ensure space is added safely,
consistently, and within the OS- and ASM-level capacity boundaries.

> Freshness: If `last_updated` is older than **90 days**, verify all procedures before
> executing in production. Update `last_updated` and increment `version` after each review.

---

## Scope and Audience

This document applies to the DBA team operating in the production environment. It is
specifically scoped to permanent, locally-managed tablespaces in an Oracle 19c database
instance and excludes UNDO tablespace management, TEMP tablespace management, and
Automatic Storage Management (ASM) disk group expansion.

| Dimension        | Value                                                                |
|------------------|----------------------------------------------------------------------|
| Environment      | Production (also applicable to Staging with same steps)              |
| Platform         | Oracle Database 19c (compatible with 12c R2 and 21c)                |
| Service          | <!-- TODO: verify — Application DB Service Name -->                  |
| Primary Team     | DBA Team — owns and executes this runbook                            |
| Secondary Team   | Linux/Storage Team — required only if OS-level disk space is needed  |

**Intended Audience:** Oracle DBAs (OCP-level or equivalent hands-on experience).
Junior DBAs must have this procedure reviewed by a Senior DBA before executing in production.

**Out of Scope:**
- UNDO (UNDOTBS) tablespace tuning or switching
- TEMP tablespace group management
- ASM disk group resizing or rebalancing
- Tablespace migration between storage tiers
- Oracle Managed Files (OMF) environments (datafile paths differ)

---

## Prerequisites

All prerequisites must be satisfied before executing any step in this document. Partial
fulfillment may cause procedure failure or unintended side effects on the target database instance.


| Tool / Package                  | Minimum Version | Purpose                                  | Install Reference                     |
|---------------------------------|-----------------|------------------------------------------|---------------------------------------|
| SQL*Plus                        | 19c client      | Execute DDL and diagnostic SQL           | Oracle Instant Client or full install |
| Oracle Enterprise Manager (OEM) | 13.5            | Optional — alert monitoring              | Internal OEM console URL              |
| df / du (Linux)                 | GNU coreutils   | Verify OS-level free disk space          | Pre-installed on all Linux hosts      |
| asmcmd                          | 19c             | Required only if storage is on ASM       | Part of Oracle Grid Infrastructure    |

### Pre-Execution Health Checks

Run these checks before starting. If any check fails, do not proceed — see Known Issues and Limitations.

```sql
-- 1. Confirm database is OPEN
SELECT instance_name, status, database_status FROM v$instance;
-- Expected: STATUS = OP### Access and Permissions

- [ ] Logged into the database host via an approved bastion/jump host
- [ ] OS user with read access to the Oracle datafile filesystem (e.g., `oracle` OS user)
- [ ] Oracle DB privilege: `SYSDBA` or `DBA` role (required for `ALTER TABLESPACE`)
- [ ] Change Management: approved change ticket opened before execution <!-- TODO: verify change management tool -->
- [ ] Notification sent to application teams if downtime window is required

### Tools and Dependencies
EN, DATABASE_STATUS = ACTIVE

-- 2. Check current tablespace usage (identify the target tablespace)
SELECT[1534]
    tsu.tablespace_name,
    ROUND(tsu.used_space * 8192 / 1073741824, 2)      AS used_gb,
    ROUND(tsu.tablespace_size * 8192 / 1073741824, 2)  AS total_gb,
    ROUND(tsu.used_percent, 2)                          AS used_pct
FROM dba_tablespace_usage_metrics tsu
ORDER BY used_pct DESC;
-- Expected: Identify tablespace with used_pct > 80% (alert threshold)

-- 3. List existing datafiles for the target tablespace
SELECT file_id, file_name, ROUND(bytes/1073741824,2) AS size_gb,
       autoextensible, ROUND(maxbytes/1073741824,2) AS max_gb
FROM dba_data_files
WHERE tablespace_name = '&TARGET_TABLESPACE'
ORDER BY file_id;
```

```bash
# 4. Verify OS-level free disk space on the datafile mount point
df -h /u02/oradata   # TODO: verify actual datafile path

# 5. Confirm no active ORA- errors in the alert log (last 100 lines)
tail -100 $ORACLE_BASE/diag/rdbms/<DB_NAME>/<SID>/trace/alert_<SID>.log | grep -i "ORA-"
```

---

## Procedure

This section contains the step-by-step procedure to extend an Oracle tablespace. Steps
must be executed in sequence. Step 3 and Step 4 are mutually exclusive — execute only
the one appropriate for your scenario (add new datafile vs. resize existing).

---

### Step 1 - Identify Target Tablespace and Extension Method/p1

Before making any changes, confirm the exact tablespace name and decide which extension
method to use. The choice between adding a new datafile and resizing an existing one
depends on the number of remaining datafile slots, OS disk layout, and current autoextend configuration.

**Trigger / Condition:** OEM/Nagios alert fired for tablespace usage > 80%, or an
`ORA-01653` / `ORA-01654` error is reported by the application team.

**Action:**

```sql
-- Check max datafiles limit vs. current count
SELECT name, value FROM v$parameter WHERE name = 'db_files';
SELECT COUNT(*) AS current_datafile_count FROM dba_data_files;

-- Check if existing files have headroom to autoextend
SELECT file_name,
       ROUND(bytes/1073741824, 2)             AS current_size_gb,
       autoextensible,
       ROUND(maxbytes/1073741824, 2)           AS max_size_gb,
       ROUND((maxbytes - bytes)/1073741824, 2) AS headroom_gb
FROM dba_data_files
WHERE tablespace_name = '&TARGET_TABLESPACE';
```

**Expected Output:**

```
FILE_NAME                          CURRENT_SIZE_GB  AUTOEXTENSIBLE  MAX_SIZE_GB  HEADROOM_GB
/u02/oradata/ORCL/users01.dbf                5.00  YES                   32.00        27.00
```

**Validation:**
Compare `HEADROOM_GB` against required free space. If headroom is sufficient but
`AUTOEXTENSIBLE = NO`, proceed to Step 3. If no headroom exists, proceed to Step 4.

> Caution: Do not rely solely on `DBA_FREE_SPACE` for locally managed tablespaces —
> use `DBA_TABLESPACE_USAGE_METRICS` for accurate readings.

---

### Step 2 - Verify OS Disk Capacity Before Extension/p1

Before adding space at the database layer, confirm the underlying filesystem has
sufficient free space. Extending a tablespace beyond available OS disk space will result
in datafile corruption or DBWn process errors.

**Trigger / Condition:** Executed immediately after Step 1, before any DDL changes.

**Action:**

```bash
# Check free space on the Oracle datafile mount point
df -hP /u02/oradata   # TODO: verify actual mount point

# Calculate total size of existing datafiles on the target filesystem
du -sh /u02/oradata/<DB_NAME>/
```

**Expected Output:**

```
Filesystem             Size  Used Avail Use% Mounted on
/dev/mapper/ora_data   500G  310G  190G  62%  /u02/oradata
```

**Validation:**
Available space must exceed the intended datafile addition size plus a 10% buffer.
Example: adding a 10 GB datafile requires at least 11 GB free.

> Caution: If the filesystem is on a SAN/NAS LUN, contact the Linux/Storage team
> before proceeding. Do not assume filesystem free space equals available SAN capacity.

---

### Step 3 - Resize Existing Datafile (Option A)

Use this step when an existing datafile has physical headroom on the filesystem and needs
to be grown. This method avoids increasing the total datafile count, which is preferable
when approaching the `DB_FILES` parameter limit. Resizing is an online operation and does
not require downtime.

**Trigger / Condition:** Step 1 confirmed that an existing datafile has `HEADROOM_GB > 0`
and either `AUTOEXTENSIBLE = NO` or the current size needs an immediate one-time increase.

**Action:**

```sql
-- Option A1: Resize an existing datafile to a specific size
ALTER DATABASE DATAFILE '/u02/oradata/ORCL/users01.dbf'
    RESIZE 15G;  -- TODO: verify target size based on capacity assessment

-- Option A2: Enable AUTOEXTEND on a datafile (set max cap to prevent runaway growth)
ALTER DATABASE DATAFILE '/u02/oradata/ORCL/users01.dbf'
    AUTOEXTEND ON
    NEXT 512M
    MAXSIZE 32G;  -- TODO: verify MAXSIZE based on filesystem capacity
```

**Expected Output:**

```
Database altered.
```

**Validation:**

```sql
-- Confirm new size is reflected
SELECT file_name, ROUND(bytes/1073741824,2) AS new_size_gb,
       autoextensible, ROUND(maxbytes/1073741824,2) AS max_size_gb
FROM dba_data_files WHERE tablespace_name = '&TARGET_TABLESPACE';

-- Re-check tablespace usage metrics
SELECT tablespace_name, ROUND(used_percent,2) AS used_pct
FROM dba_tablespace_usage_metrics WHERE tablespace_name = '&TARGET_TABLESPACE';
-- Expected: used_pct dropped below 80%
```

> Caution: Specifying a RESIZE value smaller than the current file size is destructive
> and will result in data loss if allocated extents exist in that region. Always resize upward only.

---

### Step 4 - Add New Datafile to Tablespace (Option B)

Use this step when existing datafiles are already at their maximum size or when spreading
I/O across multiple files is desired. Adding a datafile is an online DDL operation and
requires no application downtime, provided sufficient OS disk space exists.

**Trigger / Condition:** Step 1 confirmed all existing datafiles have `HEADROOM_GB = 0`
or the `DB_FILES` limit has not been reached and a new file is preferred.

**Action:**

```sql
-- Add a new datafile to the target tablespace
ALTER TABLESPACE USERS   -- TODO: verify target tablespace name
    ADD DATAFILE '/u02/oradata/ORCL/users02.dbf'  -- TODO: verify path and filename
    SIZE 10G
    AUTOEXTEND ON
    NEXT 512M
    MAXSIZE 32G;  -- TODO: verify MAXSIZE based on filesystem capacity
```

**Expected Output:**

```
Tablespace altered.
```

**Validation:**

```sql
-- Confirm new datafile appears in DBA_DATA_FILES
SELECT file_id, file_name, ROUND(bytes/1073741824,2) AS size_gb,
       autoextensible, ROUND(maxbytes/1073741824,2) AS max_size_gb
FROM dba_data_files WHERE tablespace_name = '&TARGET_TABLESPACE' ORDER BY file_id;

-- Confirm tablespace usage dropped below threshold
SELECT tablespace_name, ROUND(used_percent,2) AS used_pct
FROM dba_tablespace_usage_metrics WHERE tablespace_name = '&TARGET_TABLESPACE';
```

```bash
# Confirm new datafile exists at the OS level
ls -lh /u02/oradata/ORCL/users02.dbf
```

> Caution: Ensure the filename does not conflict with an existing file. Oracle will
> overwrite the existing file without warning if the path already exists.

---

### Step 5 - Confirm Alert Clearance and Log the Change

After extending the tablespace, confirm that monitoring alerts have cleared and document
the change in the DBA change log. Uncleared alerts may indicate the extension was
insufficient or that a secondary tablespace is also full.

**Trigger / Condition:** Executed after Step 3 or Step 4 validation confirms usage
has dropped below the alert threshold.

**Action:**

```sql
-- Final full tablespace space report for DBA change log
SELECT
    tsu.tablespace_name,
    ROUND(tsu.used_space * 8192 / 1073741824, 2)      AS used_gb,
    ROUND(tsu.tablespace_size * 8192 / 1073741824, 2)  AS total_gb,
    ROUND(tsu.used_percent, 2)                          AS used_pct,
    COUNT(df.file_id)                                   AS datafile_count
FROM dba_tablespace_usage_metrics tsu
JOIN dba_data_files df ON df.tablespace_name = tsu.tablespace_name
WHERE tsu.tablespace_name = '&TARGET_TABLESPACE'
GROUP BY tsu.tablespace_name, tsu.used_space, tsu.tablespace_size, tsu.used_percent;
```

**Expected Output:**

```
TABLESPACE_NAME   USED_GB  TOTAL_GB  USED_PCT  DATAFILE_COUNT
USERS                7.50     15.00     50.00               2
```

**Validation:**
Confirm the OEM/Nagios alert status returns to GREEN. Record in the change ticket:
tablespace name, method used, old/new total size (GB), datafile path, DBA who performed
the change, and timestamp of completion.

> Caution: No destructive side effects. This is a documentation and audit step only.

---

## Decision Matrix

Use this matrix when the procedure outcome is ambiguous or an unexpected condition is
observed during execution. This matrix covers Oracle tablespace extension in production.

| Observed Condition                             | Severity | Action to Take                                       | Escalate To                      |
|------------------------------------------------|----------|------------------------------------------------------|----------------------------------|
| used_pct drops below 80% after extension       | Info     | Proceed to Step 5 — confirm and log                  | —                                |
| ORA-01119: error creating datafile             | Warning  | Check OS disk space (Step 2); verify path exists     | Linux/Storage Team               |
| ORA-00059: max datafiles exceeded              | Critical | Increase DB_FILES parameter (requires DB restart)    | Senior DBA / DBA Manager         |
| ORA-01653/ORA-01654 persists after extend      | Critical | Check for another full tablespace; re-run Step 1     | Application Team + DBA Manager   |
| Filesystem at > 90% after datafile creation    | Critical | Initiate rollback; contact Storage team immediately  | Linux/Storage Team + DBA Manager |
| Alert does not clear after 10 minutes          | Warning  | Re-check OEM/Nagios manually; verify metrics refresh | Monitoring Team                  |

---

## Rollback and Recovery

This section defines the rollback procedure for Oracle tablespace extension. Execute the
rollback only when an error condition defined in the Decision Matrix cannot be resolved
by normal steps.

### Rollback Trigger

Rollback is required when:
- Step 3 (RESIZE) or Step 4 (ADD DATAFILE) produced an ORA- error and tablespace state is inconsistent.
- OS filesystem reached >= 95% capacity after the datafile was created.
- Application team reports data corruption symptoms within 30 minutes of the extension.

### Rollback Procedure

1. Connect to the database as SYSDBA to assess the current state.

```sql
-- Assess datafile status
SELECT file#, name, status, bytes/1048576 AS size_mb FROM v$datafile ORDER BY file#;
-- Look for files in RECOVER, OFFLINE, or UNKNOWN status
```

2. If the newly added datafile is empty (no extents allocated), drop it.

```sql
-- Drop newly added datafile ONLY if it is empty
ALTER TABLESPACE USERS    -- TODO: verify tablespace name
    DROP DATAFILE '/u02/oradata/ORCL/users02.dbf';  -- TODO: verify path
-- ORA-03264 will be raised if the file is not empty — do NOT force drop
```

3. If Step 3 RESIZE reduced the file size and data was at risk, restore from RMAN.

```bash
rman target /
```

```sql
-- Inside RMAN
RESTORE DATAFILE '/u02/oradata/ORCL/users01.dbf';  -- TODO: verify path
RECOVER DATAFILE '/u02/oradata/ORCL/users01.dbf';
ALTER DATABASE DATAFILE '/u02/oradata/ORCL/users01.dbf' ONLINE;
```

4. Free OS disk space if filesystem is critical (>= 95%).

```bash
# Only after successful DROP DATAFILE step above
rm -f /u02/oradata/ORCL/users02.dbf   # TODO: verify path
df -hP /u02/oradata
```

### Post-Rollback Validation

```sql
-- Confirm datafile count is back to pre-change state
SELECT COUNT(*) FROM dba_data_files WHERE tablespace_name = '&TARGET_TABLESPACE';

-- Confirm no files in RECOVER status
SELECT name, status FROM v$datafile;
```

```bash
tail -50 $ORACLE_BASE/diag/rdbms/<DB_NAME>/<SID>/trace/alert_<SID>.log | grep -i "ORA-"
```

**Expected post-rollback state:** All datafiles show ONLINE status. Tablespace used_pct
is at pre-change value. No ORA- errors in alert log. RMAN backup chain is intact.

---

## Monitoring and Alerting Reference

The following table lists the key observability signals for Oracle tablespace capacity.
Engineers responding to alerts should check these metrics first.

| Metric / Alert Name              | Monitoring Tool        | Threshold            | Response Action                               |
|----------------------------------|------------------------|----------------------|-----------------------------------------------|
| Tablespace Used %                | OEM / Nagios / Zabbix  | Warning > 80%        | Execute this runbook                          |
| Tablespace Used %                | OEM / Nagios / Zabbix  | Critical > 90%       | Execute this runbook immediately              |
| Datafile Status (non-ONLINE)     | OEM / Custom SQL probe | Any non-ONLINE file  | Investigate V$DATAFILE, page DBA on-call      |
| OS Filesystem Usage              | Zabbix / CloudWatch    | Warning > 80%        | Notify Linux/Storage team                     |
| ORA-01653 / ORA-01654 in app log | Log aggregation (ELK)  | Any occurrence       | Trigger this runbook; notify application team |
| RMAN Backup Success              | OEM / RMAN log         | Any FAILED backup    | Resolve before executing any datafile change  |

---

## Security Considerations

- **Credentials:** Retrieve from approved vault (HashiCorp Vault / CyberArk). Never store in plain text. <!-- TODO: verify vault tool -->
- **Blast Radius:** Incorrect RESIZE (downward) causes irreversible data loss. Wrong ADD DATAFILE path can overwrite an existing file.
- **Least Privilege:** Use a named DBA account with ALTER TABLESPACE privilege. Avoid SYSDBA unless RMAN restore is required.
- **Audit Logging:** Oracle Unified Auditing captures ALTER TABLESPACE and ALTER DATABASE DDL events. Verify via UNIFIED_AUDIT_TRAIL after execution.
- **Compliance:** Pre-approved change record mandatory before production execution. Reference: ../pmo/POLICY-change-mgmt.md <!-- TODO: verify path -->

---

## Known Issues and Limitations

- **Issue:** ORA-00059 — maximum number of datafiles exceeded
  - **Affected Versions / Environments:** All Oracle versions; DB_FILES limit reached.
  - **Workaround:** `ALTER SYSTEM SET DB_FILES = <new_value> SCOPE=SPFILE;` then controlled DB restart.
  - **Ticket / Reference:** Oracle Doc ID 1271722.1

- **Issue:** ORA-01119 — error creating datafile even when OS reports free space
  - **Affected Versions / Environments:** ASM or NFS-mounted storage environments.
  - **Workaround:** Verify ASM disk group via `asmcmd lsdg` or check NFS export quotas.
  - **Ticket / Reference:** Oracle Doc ID 429786.1

- **Issue:** Tablespace usage % in OEM does not update immediately after extension
  - **Affected Versions / Environments:** OEM 13.5 with 10-minute MMON collection interval.
  - **Workaround:** Query DBA_TABLESPACE_USAGE_METRICS directly from SQL*Plus for real-time values.
  - **Ticket / Reference:** Internal monitoring team knowledge base.

- **Issue:** ALTER TABLESPACE ... DROP DATAFILE fails with ORA-03264
  - **Affected Versions / Environments:** All Oracle versions — file contains allocated extents.
  - **Workaround:** Use Data Pump export/import to consolidate before dropping. Escalate to Senior DBA.
  - **Ticket / Reference:** Oracle Doc ID 1266007.1

---

## Glossary

| Term / Acronym | Full Expansion                         | Definition                                                                              |
|----------------|----------------------------------------|-----------------------------------------------------------------------------------------|
| TBS            | Tablespace                             | Logical storage unit in Oracle composed of one or more physical datafiles.               |
| DBA            | Database Administrator                 | Role responsible for Oracle database maintenance and operations.                         |
| DDL            | Data Definition Language               | SQL statements modifying database structure (e.g., ALTER TABLESPACE, CREATE TABLE).     |
| DML            | Data Manipulation Language             | SQL statements reading or modifying data (INSERT, UPDATE, DELETE).                      |
| SYSDBA         | System DBA Privilege                   | Oracle highest-privilege connection mode, required for startup/shutdown and recovery.    |
| RMAN           | Recovery Manager                       | Oracle native backup and recovery tool.                                                  |
| ASM            | Automatic Storage Management           | Oracle integrated volume manager and file system for database files.                     |
| OEM            | Oracle Enterprise Manager              | Oracle GUI-based database monitoring and management console.                             |
| MMON           | Manageability Monitor Process          | Oracle background process collecting AWR snapshots.                                      |
| AWR            | Automatic Workload Repository          | Oracle repository of historical performance and capacity data.                           |
| OMF            | Oracle Managed Files                   | Feature where Oracle auto-generates datafile paths; not covered by this runbook.         |
| SAN            | Storage Area Network                   | Dedicated high-speed network for block-level storage.                                    |
| ORA-01653      | Oracle Error 01653                     | Unable to extend table in tablespace — permanent tablespace is full.                    |
| ORA-01654      | Oracle Error 01654                     | Unable to extend index in tablespace — same root cause as ORA-01653 but for indexes.    |
| ORA-00059      | Oracle Error 00059                     | Maximum number of datafiles exceeded — DB_FILES parameter limit reached.                |

---

## References and External Links

| Resource                                  | URL / Path                                                                                        | Notes                                      |
|-------------------------------------------|---------------------------------------------------------------------------------------------------|--------------------------------------------|
| Oracle 19c ALTER TABLESPACE               | https://docs.oracle.com/en/database/oracle/oracle-database/19/sqlrf/ALTER-TABLESPACE.html        | Official DDL syntax reference              |
| Oracle 19c DBA_DATA_FILES                 | https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/DBA_DATA_FILES.html          | Column reference for datafile queries      |
| Oracle 19c DBA_TABLESPACE_USAGE_METRICS   | https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/DBA_TABLESPACE_USAGE_METRICS.html | Space usage metrics view              |
| Oracle Support Doc 1271722.1              | https://support.oracle.com                                                                        | DB_FILES parameter — MOS login required    |
| Oracle Support Doc 429786.1               | https://support.oracle.com                                                                        | ORA-01119 — MOS login required             |
| Internal Change Management Policy         | ../pmo/POLICY-change-mgmt.md                                                                      | Required approval before production DDL    |
| RMAN Backup Runbook                       | ../dba/DBA-RUNBOOK-oracle-rman-backup-2026-03-29.md                                               | Ensure valid backup before this runbook    |

---

## DBA Team - Database Environment Reference

This section provides the database-layer reference for the target Oracle instance. All
connection parameters marked TODO must be confirmed against the current CMDB and DBA
runbook registry before approval.

### Database Environment Context

| Parameter          | Value                                                               |
|--------------------|---------------------------------------------------------------------|
| DBMS Engine        | Oracle Database 19c (19.x.x.x)                                     |
| Instance / SID     | <!-- TODO: verify — e.g., ORCL / PRODDB -->                        |
| Host / Endpoint    | <!-- TODO: verify — e.g., db-prod-01.internal -->                  |
| Port               | 1521                                                                |
| Schema / Database  | <!-- TODO: verify — affected schema(s) -->                         |
| High Availability  | <!-- TODO: verify — RAC / Data Guard / None -->                    |
| DBA Contact        | <!-- TODO: verify — Name / on-call rotation / PagerDuty policy --> |

### Connection Reference

```sql
-- Connect as SYSDBA (use only when required — Steps 3, 4 and rollback)
sqlplus sys/<password>@<TNS_ALIAS> as sysdba  -- TODO: verify TNS_ALIAS

-- Connect as DBA user (preferred for diagnostic queries — Steps 1, 2, 5)
sqlplus <dba_user>/<password>@<TNS_ALIAS>     -- TODO: verify DBA user
```

### Key Object Inventory

| Object Type      | Name                                     | Purpose                                          |
|------------------|------------------------------------------|--------------------------------------------------|
| Tablespace / TBS | <!-- TODO: verify target TBS name -->    | Storage allocation for application objects       |
| Datafile         | <!-- TODO: verify current file paths --> | Physical files backing the target tablespace     |
| Tablespace / TBS | UNDOTBS1                                 | Undo tablespace — out of scope for this runbook  |
| Tablespace / TBS | TEMP                                     | Temp tablespace — out of scope for this runbook  |

### Space and Performance Baseline

| Metric               | Expected Value          | Check Query / Tool                                   |
|----------------------|-------------------------|------------------------------------------------------|
| Tablespace Free (%)  | > 20%                   | DBA_TABLESPACE_USAGE_METRICS                         |
| Active Sessions      | < TODO: verify          | SELECT COUNT(*) FROM v$session WHERE status='ACTIVE' |
| Long-Running Queries | 0 queries > 60s         | V$SQL ordered by ELAPSED_TIME                        |
| Redo Log Switch Rate | < 4/hour                | V$LOG_HISTORY (GROUP BY TRUNC(FIRST_TIME,'HH'))      |
| Replication Lag      | < 10s                   | V$DATAGUARD_STATS (if Data Guard in use)             |

---

## Revision History

| Version | Date       | Author                          | Status | Change Summary                               |
|---------|------------|---------------------------------|--------|----------------------------------------------|
| 1.0.0   | 2026-03-29 | DBA Team (OI Platform Doc Init) | Draft  | Initial draft — tablespace extension runbook |
