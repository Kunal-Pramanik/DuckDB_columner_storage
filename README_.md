# 🦆 DS614: Big Data Engineering — DuckDB Columnar Storage Engine Analysis

**Course:** DS614 — Big Data Engineering  
**Topic:** DuckDB – Columnar Storage Engine Analysis  
**Guide:** Prof. Ankush Chander  
**Members:** Kunal Pramanik · Jinal Sasiya  
**Institution:** DAU, Semester 2  
**System Analyzed:** DuckDB — In-Process Analytical Columnar Database  
**DuckDB Source:** [duckdb/duckdb](https://github.com/duckdb/duckdb)

---

## 📋 Table of Contents

1. [What is DuckDB?](#1-what-is-duckdb)
2. [Why This Experiment? — The Problem We Investigated](#2-why-this-experiment--the-problem-we-investigated)
3. [Core Modification](#3-core-modification)
4. [Repository Structure](#4-repository-structure)
5. [Important Background Concepts](#5-important-background-concepts)
   - [Physical Blocks](#physical-blocks)
   - [Row Groups](#row-groups)
   - [Vectorized Execution](#vectorized-execution)
6. [Modified Write Path](#6-modified-write-path)
7. [Concept Mapping](#7-concept-mapping)
8. [Experiments Overview](#8-experiments-overview)
9. [Experiments — Deep Dive](#9-experiments--deep-dive)
   - [Experiment 1: Sequential Scan Performance](#experiment-1-sequential-scan-performance)
   - [Experiment 2: WAL Growth Analysis](#experiment-2-wal-growth-analysis)
   - [Experiment 3: Row Group Fill Density](#experiment-3-row-group-fill-density)
   - [Experiment 4: VACUUM Stability Test](#experiment-4-vacuum-stability-test)
   - [Experiment 5: Self-Join Stress Test](#experiment-5-self-join-stress-test)
   - [Experiment 6: Vector Alignment Analysis](#experiment-6-vector-alignment-analysis)
   - [Experiment 7: BufferManager Pressure Test](#experiment-7-buffermanager-pressure-test)
   - [Experiment 8: Cache Locality Analysis](#experiment-8-cache-locality-analysis)
   - [Experiment 9: Fragmented Insert Workload](#experiment-9-fragmented-insert-workload)
   - [Experiment 10: Checkpoint Flush Analysis](#experiment-10-checkpoint-flush-analysis)
10. [Failure Analysis](#10-failure-analysis)
11. [Key Insights & Conclusions](#11-key-insights--conclusions)
12. [How to Clone & Reproduce — Full Setup Guide](#12-how-to-clone--reproduce--full-setup-guide)
13. [Credits](#13-credits)

---

## 1. What is DuckDB?

DuckDB is a free, open-source, in-process SQL database designed specifically for analytical workloads (OLAP). It runs entirely inside your application process — no server, no network overhead, no daemon to manage.

Think of it as **SQLite for analytics**: just like SQLite stores a database in a single file and needs no server, DuckDB does the same but is optimized for scanning millions of rows and computing aggregations — not for small transactional reads and writes.

### Key Characteristics

| Property | Value |
|---|---|
| Type | In-process OLAP SQL database |
| Storage format | Columnar (column-per-file) |
| Execution model | Vectorized push-based batches |
| Language | C++, with Python/R/Java/Node bindings |
| Concurrent writes | Single-writer, multiple-reader |
| Best use case | Analytical queries on 1 MB – 100 GB datasets |
| License | MIT |

### Where DuckDB Sits in the Database Landscape

```
                OLTP (Transactions)        OLAP (Analytics)
                ───────────────────        ────────────────
 Server-based   PostgreSQL, MySQL    ←→    Snowflake, BigQuery
 In-process     SQLite               ←→    DuckDB  ✓
```

DuckDB fills the bottom-right quadrant: analytical queries that run locally, without cloud infrastructure, without a running server, embedded directly into Python notebooks, data pipelines, or application code.

### What DuckDB Can Do

```python
import duckdb

# Query a Parquet file directly — no loading required
duckdb.sql("SELECT SUM(quantity), region FROM 'sales.parquet' GROUP BY region")

# Query a Pandas DataFrame as if it were a table
import pandas as pd
df = pd.read_csv("orders.csv")
duckdb.sql("SELECT customer_id, SUM(amount) FROM df GROUP BY customer_id")
```

---

## 2. Why This Experiment? — The Problem We Investigated

DuckDB defaults to **256 KB physical storage blocks**. This is not an arbitrary configuration value — it is a carefully tuned constant that co-designed with vectorized execution, the BufferManager, WAL design, and CPU cache architecture.

**Our question:** What happens when you violate this assumption?

We reduced the block size from **256 KB to 4 KB** — a 64× reduction — and left every other part of the engine unchanged. By isolating this single variable, we could observe exactly how the storage layer's assumptions propagate through fragmentation, metadata overhead, cache behavior, and write amplification.

### The Three Problems Small Blocks Create

**Problem 1 — Metadata explosion**
At 256 KB, a 1 million-row scan touches ~4 blocks. At 4 KB, the same scan touches ~250 blocks — each requiring a block header lookup, pointer dereference, and BufferManager pin. Metadata overhead scales 64×.

**Problem 2 — Vector-block alignment breaks**
DuckDB's default vector size is 2048 elements ≈ 16 KB. With 256 KB blocks, an entire vector fits inside one block. With 4 KB blocks, one vector spans **4 physical blocks** — the engine cannot guarantee contiguous memory without costly copies, breaking SIMD efficiency.

**Problem 3 — WAL and checkpoint amplification**
Every block boundary creates a WAL marker and a checkpoint entry. 64× more blocks means 64× more WAL transitions, 64× more checkpoint footer entries, and 64× longer checkpoint pauses — directly impacting transactional write throughput.

> The goal was not to break DuckDB — it was to understand *why* those design choices exist by seeing what changes when they are removed.

---

## 3. Core Modification

**Modified file:**
```
src/include/duckdb/storage/storage_info.hpp
```

### Original (default DuckDB)
```cpp
#define STORAGE_BLOCK_SIZE (1024 * 256)   // 262,144 bytes = 256 KB
```

### Modified (our experiment)
```cpp
#define STORAGE_BLOCK_SIZE (4096)          // 4,096 bytes = 4 KB
```

This is a **64× reduction** in physical block granularity. Every other part of the engine — Row Groups, vectorized execution, WAL, BufferManager — was left unchanged, so we could observe exactly what breaks and why.

---

## 4. Repository Structure

```
DuckDB_columner_storage/
├── duckdb/                          # Modified DuckDB source (custom fork)
│   └── src/
│       └── include/
│           └── duckdb/
│               └── storage/
│                   └── storage_info.hpp   ← Core modification here
├── charts/                          # Output charts from experiments
│   ├── exp1_column_scan.png
│   ├── exp2_compression.png
│   ├── exp3_scalability.png
│   ├── exp4_skew.png
│   └── exp5_write.png
├── experiments.py                   # All 6 Python experiments with charts
├── DuckDB_Columnar_Storage.pptx     # Presentation deck
└── README.md
```

---

## 5. Important Background Concepts

### Physical Blocks

Physical blocks are the smallest storage units the database engine reads from and writes to disk. DuckDB's default 256 KB block size is carefully tuned to:

- Match typical OS page cache behavior
- Minimize the metadata-per-byte ratio
- Align with SSDs' optimal sequential write unit
- Fit comfortably in L2/L3 CPU cache during scans

### Row Groups

DuckDB internally organizes columnar data into **Row Groups**, each containing exactly 122,880 rows. Row Groups are the logical unit of statistics, compression, and parallel execution. Crucially, Row Groups exist *above* the physical block layer — changing block size does not change Row Group boundaries.

```
122,880 rows per Row Group
```

### Vectorized Execution

DuckDB processes data in vectors (batches) rather than row by row. The default vector size is:

```
2048 elements ≈ 16 KB for double columns
```

With 256 KB blocks, a single vector fits comfortably inside one block. With 4 KB blocks, one vector spans **4 physical blocks** — forcing the engine to pin/unpin across multiple block boundaries to process a single operation.

---

## 6. Modified Write Path

```
SQL Input
   ↓
Parser
   ↓
Planner
   ↓
PhysicalInsert::Execute()
   ↓
ColumnData::Append()
   ↓
BlockManager::CreateBlock()       ← Block size used here
   ↓
CheckpointManager / WAL           ← More blocks = more WAL entries
   ↓
Flush to .duckdb file
```

> **Core Principle:** If you cannot point to code, you have not understood the system.

The storage layer touched by our modification spans six source files:

| File | Role in Write Path |
|---|---|
| `src/include/duckdb/storage/storage_info.hpp` | Block size constant — **our modification** |
| `src/storage/buffer/buffer_manager.cpp` | Pin/unpin logic, pool eviction |
| `src/storage/checkpoint/write_overflow_strings_to_disk.cpp` | Checkpoint serialization |
| `src/storage/column_data.cpp` | Column append path |
| `src/storage/table/row_group.cpp` | Row Group management |
| `src/transaction/wal_write_state.cpp` | WAL entry generation |

---

## 7. Concept Mapping

| Concept (from DS614) | How DuckDB Implements It | Code Location |
|---|---|---|
| Columnar Storage | Data stored column-by-column in contiguous memory. Only queried columns are loaded from disk. Physical block size controls how much data is read per I/O operation. | `src/storage/column_data.cpp` |
| Batch Processing | Data flows through the engine in DataChunk micro-batches of 2048 rows. Block size determines whether a full batch fits within one physical read. | `src/common/types/data_chunk.cpp` |
| Memory Hierarchy Awareness | The 256 KB block is co-designed with vector size and CPU cache size. Reducing it to 4 KB breaks the alignment between physical I/O and logical computation units. | `src/include/duckdb/storage/storage_info.hpp` |
| Write-Ahead Logging | Every block boundary generates a WAL entry. 64× more blocks = 64× more WAL overhead per insert. | `src/transaction/wal_write_state.cpp` |
| Buffer Management | BufferManager tracks all live blocks with pin/unpin cycles. 64× more blocks = 64× more pool pressure, more evictions, more CPU overhead. | `src/storage/buffer/buffer_manager.cpp` |
| Checkpoint / Recovery | CheckpointManager serializes all dirty blocks. More blocks = larger checkpoint footer, longer pause time, slower recovery. | `src/storage/checkpoint/` |

---

## 8. Experiments Overview

We ran **10 experiments** to systematically cover every layer the block size change touches — 6 engine-level (C++/DuckDB shell) and 6 Python-level (via the DuckDB Python API).

| # | Experiment | Type | Key Question |
|---|---|---|---|
| 1 | Sequential Scan Performance | Engine-level | How much does scan throughput degrade with 64× more blocks? |
| 2 | WAL Growth Analysis | Engine-level | How does fragmentation amplify write-ahead log overhead? |
| 3 | Row Group Fill Density | Engine-level | Do Row Groups fragment when physical block size changes? |
| 4 | VACUUM Stability Test | Engine-level | Can DuckDB reclaim space after deletions under small blocks? |
| 5 | Self-Join Stress Test | Engine-level | How does metadata overhead compound under complex queries? |
| 6 | Vector Alignment Analysis | Engine-level | What happens when vectors no longer fit inside one block? |
| 7 | BufferManager Pressure Test | Engine-level | How much extra overhead does the BufferManager carry? |
| 8 | Cache Locality Analysis | Engine-level | How does block fragmentation affect CPU cache hit rates? |
| 9 | Fragmented Insert Workload | Engine-level | How does write amplification scale with block count? |
| 10 | Checkpoint Flush Analysis | Engine-level | How does checkpoint pause time grow with 64× more blocks? |

**Python experiments** (`experiments.py`):

| Exp | What It Measures | Output |
|---|---|---|
| Exp 1 | Column scan vs full row scan (10M rows) | `exp1_column_scan.png` |
| Exp 2 | Compression ratios by data distribution | `exp2_compression.png` |
| Exp 3 | Query time vs dataset size (100K–25M rows) | `exp3_scalability.png` |
| Exp 4 | GROUP BY under uniform vs skewed data | `exp4_skew.png` |
| Exp 5 | INSERT performance by batch size | `exp5_write.png` |
| Exp 6 | EXPLAIN ANALYZE — physical query plan | *(stdout)* |

---

## 9. Experiments — Deep Dive

### Experiment 1: Sequential Scan Performance

**Target:** Measure analytical query slowdown caused by fragmented blocks.

**DuckDB source files involved:**
- `src/storage/column_data.cpp` — column read path
- `src/storage/buffer/buffer_manager.cpp` — block pin/unpin on scan

**Query run:**
```sql
SELECT SUM(val) FROM perf_test;
```

**Results:**

| Configuration | Time |
|---|---|
| 256 KB Blocks | 0.025s |
| 4 KB Blocks | 0.030s |

**Analysis:** With 256 KB blocks, a 1 million-row column scan touches ~4 blocks. With 4 KB blocks, the same scan touches ~250 blocks — each requiring a block header lookup, a pointer dereference into the BufferManager, and a page pin. This multiplies cache misses and BufferManager overhead by the block count ratio.

**Insight:** Large blocks are critical for analytical scan efficiency. The 256 KB default is not arbitrary — it matches the typical size at which sequential I/O amortizes metadata cost.

---

### Experiment 2: WAL Growth Analysis

**Target:** Analyze how fragmentation inflates write-ahead log overhead.

**DuckDB source files involved:**
- `src/transaction/wal_write_state.cpp` — WAL marker generation per block

**Result:** The `.wal` file grew significantly faster with 4 KB blocks.

**Analysis:** Each block boundary generates a WAL marker. With 64× more blocks, the WAL must record 64× more page transitions, metadata entries, and fragmented write boundaries per data insert. For transactional workloads, this means proportionally more I/O on recovery paths and during checkpointing.

**Insight:** Fragmentation is not just a read-time problem — it directly amplifies transactional write overhead.

---

### Experiment 3: Row Group Fill Density

**Target:** Verify whether Row Groups fragment when physical blocks change.

**DuckDB source files involved:**
- `src/storage/table/row_group.cpp` — Row Group management (logical layer)

**Result:** Both configurations showed identical fill density:

```
122,880 / 1,000,000 = 12.288%
```

**Analysis:** Row Groups are a *logical* abstraction maintained above the physical storage layer. `RowGroupCollection` and `ColumnData` do not change their row-grouping behavior based on `STORAGE_BLOCK_SIZE`. The logical organization is preserved even when the physical substrate is fragmented.

**Insight:** DuckDB's architectural separation between logical Row Groups and physical blocks is robust. This is a deliberate design — the optimizer and statistics layer remain stable across storage configurations.

---

### Experiment 4: VACUUM Stability Test

**Target:** Analyze storage reclamation after mass deletion.

**Procedure:** Inserted 1M rows, deleted 90%.

**Result:** Even after deleting 90% of rows, file size remained at **18.2 MB**.

**Analysis:** DuckDB cannot truncate a physical block if even one row within it is still live. With 4 KB blocks, deleted rows are distributed more thinly across more blocks — meaning more blocks remain "pinned" by a single survivor row. This is *sparse block pinning* and is worse under small block sizes.

**Insight:** This is the physical manifestation of the row group tombstone problem. Production systems need compaction/rewrite passes (equivalent to `VACUUM FULL` in PostgreSQL) to reclaim space.

---

### Experiment 5: Self-Join Stress Test

**Target:** Stress metadata management and BufferManager under complex query patterns.

**DuckDB source files involved:**
- `src/storage/buffer/buffer_manager.cpp` — pin/unpin per re-scan
- `src/execution/operator/join/` — join operator re-scanning column data

**Result:** Execution time increased dramatically with 4 KB blocks.

**Analysis:** A self-join requires the engine to scan the same column data multiple times while maintaining join state. With 4 KB blocks, each re-scan hits the BufferManager more times, triggers more pin/unpin cycles, and evicts more entries from the buffer pool. Metadata traversal cost becomes larger than the actual computation.

**Insight:** For complex queries, metadata overhead can dominate. The BufferManager is designed around large blocks — the ratio of metadata cost to data processed must remain small.

---

### Experiment 6: Vector Alignment Analysis

**Target:** Analyze the cache impact when vectors no longer align with blocks.

**DuckDB source files involved:**
- `src/common/types/data_chunk.cpp` — DataChunk layout
- `src/include/duckdb/common/vector_size.hpp` — STANDARD_VECTOR_SIZE = 2048

**Calculation:**

```
Default vector size: 2048 × 8 bytes (double) = 16 KB
4 KB block size → 1 vector spans 4 physical blocks
```

**Result:** Vectorized operations that previously processed data entirely within one block now cross block boundaries, requiring multiple buffer pool lookups per vector.

**Analysis:** DuckDB's SIMD and auto-vectorization depend on data being contiguous in memory. When a vector crosses a block boundary, the engine cannot guarantee memory contiguity without an intermediate copy step, destroying cache line efficiency.

**Insight:** The 256 KB block size was chosen partly to ensure that multiple vectors fit inside a single block, eliminating cross-boundary fragmentation entirely.

---

### Experiment 7: BufferManager Pressure Test

**Target:** Measure how much additional overhead the BufferManager carries under fragmentation.

**DuckDB source files involved:**
- `src/storage/buffer/buffer_manager.cpp` — LRU clock eviction

**Result:** Pin/unpin operations increased proportionally to the block count increase (approximately 64×).

**Analysis:** The BufferManager maintains a fixed-size pool of pinned blocks. With 64× more blocks for the same data, the pool fills up faster, eviction runs more frequently, and the LRU clock cycles more aggressively — even for queries that were previously well within the buffer budget.

**Insight:** BufferManager pressure is not just about memory — frequent eviction burns CPU cycles. Fragmented storage creates a hidden CPU tax.

---

### Experiment 8: Cache Locality Analysis

**Target:** Measure CPU cache behavior during scans.

**Result:** 4 KB block storage showed significantly worse cache hit rates.

**Analysis:** When data from a single column is scattered across 64× more block headers and metadata structures, the CPU cache must hold all of that metadata simultaneously to execute a scan. This crowds out actual column data from L1/L2 cache, causing thrashing.

```
Each 4 KB block header: block ID + reference count + dirty flag + next-block pointer
At 256 KB: header overhead is negligible relative to data
At 4 KB:  64× more headers compete for L1/L2 cache during a single scan
```

**Insight:** Analytical databases rely on the "streaming" memory access pattern — reading one column sequentially so the hardware prefetcher can run ahead. Fragmentation breaks this pattern.

---

### Experiment 9: Fragmented Insert Workload

**Target:** Measure write amplification under fragmented block sizes.

**DuckDB source files involved:**
- `src/storage/column_data.cpp` — column append path
- `src/transaction/wal_write_state.cpp` — WAL entry per block

**Result:** Insert operations generated significantly more fragmented writes — each batch touched more blocks, wrote more WAL entries, and updated more metadata structures.

**Analysis:**

```
A 1 MB insert:
  256 KB blocks → ~4 blocks  → 4 headers, 4 WAL markers, 4 BufferManager registrations
  4 KB blocks   → ~256 blocks → 256 headers, 256 WAL markers, 256 registrations

A 100 MB batch insert:
  256 KB → ~400 blocks
  4 KB   → ~25,600 blocks
```

**Insight:** Columnar stores are designed for bulk inserts. Even under batch inserts, fragmentation amplifies every write by the block-count multiplier.

---

### Experiment 10: Checkpoint Flush Analysis

**Target:** Analyze how checkpoint flushing behaves under fragmentation.

**DuckDB source files involved:**
- `src/storage/checkpoint/write_overflow_strings_to_disk.cpp` — dirty block serialization

**Result:** Checkpoint flushing became metadata-heavy — `CheckpointManager` had to serialize and flush significantly more block descriptors, requiring more I/O and longer checkpoint pauses.

**Analysis:** `CheckpointManager::WriteData()` iterates over all dirty blocks and flushes them to the `.duckdb` file. With 4 KB blocks, "all dirty blocks" means 64× more entries to iterate, 64× more fsync-able units, and 64× more footer metadata to write.

**Insight:** In production, checkpoint pause time directly impacts query latency. Fragmentation turns a fast checkpoint into a long one.

---

## 10. Failure Analysis

| Failure Case | Root Cause | Related Experiment |
|---|---|---|
| Metadata Thrashing | 64× more blocks → 64× more pin/unpin cycles | Experiment 5 |
| Vector Alignment Mismatch | 16 KB vectors split across 4 KB blocks | Experiment 6 |
| BufferManager Pressure | Pool eviction rate exceeded sustainable threshold | Experiment 7 |
| Cache Locality Breakdown | Column data crowded out of cache by metadata | Experiment 8 |
| Fragmented Write Amplification | Each insert boundary multiplied 64× | Experiment 9 |
| Checkpoint Metadata Explosion | Checkpoint must enumerate all 64× blocks | Experiment 10 |

### Failure 1: What Happens to Storage Reclamation?
**Experiment:** VACUUM Stability Test (Experiment 4)

DuckDB cannot reclaim a block until every row within it is deleted. With 4 KB blocks, a single survivor row pins the entire block — meaning deleting 90% of rows still leaves 100% of the file's physical blocks live. This *sparse block pinning* worsens linearly with block count.

**Where the assumption breaks:** Production systems must run compaction passes (rewrite all live rows into fresh blocks, discard old ones) to reclaim space. DuckDB does not do this automatically.

### Failure 2: What Structural Assumptions Does DuckDB Rely On?
**Experiment:** Vector Alignment Analysis (Experiment 6)

DuckDB's vectorization advantage rests on two assumptions. When either is violated, performance degrades:

| Assumption | What Code Relies On It | What Violates It | Measured Impact |
|---|---|---|---|
| Vector fits inside one block | `data_chunk.cpp` memory layout | 4 KB blocks with 16 KB vectors | Cross-boundary copy overhead |
| Sequential memory access | Tight expression executor loops | Small blocks scatter column data | Cache thrashing, prefetcher failure |

### Failure 3: What Happens When Block Count Explodes?
**Experiment:** Checkpoint Flush Analysis (Experiment 10)

`CheckpointManager` performs O(N_blocks) work at every checkpoint. With 64× more blocks, checkpoint pause time grows by 64×. This is not a corner case — every write workload triggers periodic checkpoints, and long checkpoint pauses directly stall concurrent queries.

---

## 11. Key Insights & Conclusions

| Finding | Validated By | Implication |
|---|---|---|
| DuckDB's abstraction layers are robust | Exp 3: Row Groups unchanged | Logical/physical separation is genuine — query semantics survive even when physical storage is degraded |
| 256 KB encodes hardware knowledge | Exp 6: vector-block alignment breaks at 4 KB | The block size is not a tuning knob — it is a co-design constant with vector size and cache architecture |
| Metadata is the hidden bottleneck | Exp 5, 7, 8, 10: all trace to block count | In analytical databases, the ratio of metadata cost to data processed must remain small |
| Fragmentation amplifies every layer | Exp 2, 9: WAL and write amplification | Storage design decisions propagate through reads, writes, recovery, and checkpoint — nothing is isolated |

### How to Improve DuckDB for These Failure Cases

- **VACUUM / Compaction:** Add a `COMPACT` operation that rewrites all live rows into fresh full-sized blocks, discarding sparse pinned blocks.
- **Adaptive block sizing:** Allow operators to hint the desired block size for specific access patterns (e.g., larger blocks for sequential scans, smaller for random-access joins).
- **WAL compression:** Batch WAL markers at the Row Group level instead of the physical block level to reduce log amplification under small block sizes.
- **Checkpoint incremental flush:** Flush only recently-dirtied blocks rather than all blocks, reducing checkpoint pause time proportionally.

DuckDB's correctness is not fragile — it survived a 64× block size reduction without a single incorrect result. Its *performance*, however, depends on a carefully maintained set of physical contracts. Break one contract, and the degradation is measurable, predictable, and traceable directly to the design decision that was violated.

---

## 12. How to Clone & Reproduce — Full Setup Guide

### System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 + MSVC 2019 or Ubuntu 20.04+ | Windows 11 + MSVC 2022 |
| RAM | 4 GB | 8 GB+ |
| Disk | 5 GB free | 10 GB free |
| Python | 3.8+ | 3.10+ |
| C++ compiler | MSVC 2019 / GCC 9+ | MSVC 2022 / GCC 12 |
| CMake | 3.15+ | 3.22+ |
| Build time | — | 15–30 min (Windows) |

### Step 1: Clone This Repository

```bash
git clone https://github.com/<your-repo>/DuckDB_columner_storage.git
cd DuckDB_columner_storage
```

### Step 2: Clone DuckDB Source Code

```bash
# From inside DuckDB_columner_storage/
git clone https://github.com/duckdb/duckdb.git
```

After cloning, verify your directory structure:

```
DuckDB_columner_storage/
├── duckdb/                              ← DuckDB source (just cloned)
│   └── src/
│       └── include/
│           └── duckdb/
│               └── storage/
│                   └── storage_info.hpp ← Modify this for the experiment
├── charts/
├── experiments.py
└── README.md
```

### Step 3: Apply the Core Modification

Open `duckdb/src/include/duckdb/storage/storage_info.hpp` and change:

```cpp
// Original
#define STORAGE_BLOCK_SIZE (1024 * 256)   // 256 KB

// Modified
#define STORAGE_BLOCK_SIZE (4096)          // 4 KB
```

### Step 4: Build the Modified Engine

**Windows (MSVC 2022):**

```bat
cd duckdb
cmake -S . -B out/build/x64-Release -G "Visual Studio 17 2022" -A x64
cmake --build out/build/x64-Release --config Release
```

**Linux/macOS:**

```bash
cd duckdb
cmake -B build -S . -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
```

### Step 5: Launch the Modified DuckDB Shell

**Windows:**
```bat
.\out\build\x64-Release\duckdb.exe modified_wal.db
```

**Linux/macOS:**
```bash
./build/duckdb modified_wal.db
```

### Step 6: Run Engine-Level Experiments (Inside DuckDB Shell)

**Sequential Scan (Experiment 1):**
```sql
.timer on

CREATE TABLE perf_test AS
SELECT range AS val FROM range(1000000);

CHECKPOINT;

SELECT SUM(val) FROM perf_test;
```

**Metadata Inspection:**
```sql
SELECT segment_type, count(*)
FROM pragma_storage_info('perf_test')
GROUP BY segment_type;
```

**VACUUM Test (Experiment 4):**
```sql
CREATE TABLE vac_test AS SELECT range AS id FROM range(1000000);
DELETE FROM vac_test WHERE id % 10 != 0;   -- delete 90%
CHECKPOINT;
-- Then check file size on disk
```

**Self-Join Stress Test (Experiment 5):**
```sql
CREATE TABLE join_test AS SELECT range AS id, random() AS val FROM range(500000);
SELECT a.id, SUM(b.val)
FROM join_test a JOIN join_test b ON a.id = b.id
GROUP BY a.id
LIMIT 10;
```

### Step 7: Install Python Dependencies

```bash
pip install duckdb pandas numpy matplotlib
```

### Step 8: Run Python Experiments

```bash
python experiments.py
```

Charts will be saved to `./charts/`.

### Step 9: Restore Original Block Size

To restore DuckDB to its default 256 KB configuration:

```bash
cd duckdb && git checkout src/include/duckdb/storage/storage_info.hpp
```

Then rebuild (Step 4) to benchmark the baseline.

### Quick Reference: All Commands

```bash
# ── One-time setup ──────────────────────────────────────────────────────────
git clone https://github.com/<your-repo>/DuckDB_columner_storage.git
cd DuckDB_columner_storage
git clone https://github.com/duckdb/duckdb.git
pip install duckdb pandas numpy matplotlib

# ── Apply modification ───────────────────────────────────────────────────────
# Edit duckdb/src/include/duckdb/storage/storage_info.hpp
# Change STORAGE_BLOCK_SIZE to 4096

# ── Build (Windows) ──────────────────────────────────────────────────────────
cd duckdb
cmake -S . -B out/build/x64-Release -G "Visual Studio 17 2022" -A x64
cmake --build out/build/x64-Release --config Release
cd ..

# ── Engine experiments (DuckDB shell) ────────────────────────────────────────
.\duckdb\out\build\x64-Release\duckdb.exe modified_wal.db

# ── Python experiments ────────────────────────────────────────────────────────
python experiments.py

# ── Restore original ──────────────────────────────────────────────────────────
cd duckdb && git checkout src/include/duckdb/storage/storage_info.hpp
```

### Troubleshooting

| Problem | Solution |
|---|---|
| `cmake: command not found` | Install from cmake.org or `brew install cmake` (macOS) |
| `duckdb` Python module not found | `pip install duckdb` |
| Build fails: C++ errors | Ensure MSVC 2019+ or GCC ≥ 9: `g++ --version` |
| Source left modified after crash | `cd duckdb && git checkout src/include/duckdb/storage/storage_info.hpp` |
| Out of disk during build | DuckDB build needs ~3 GB. Free space and retry. |
| Charts not generated | Ensure `matplotlib` installed: `pip install matplotlib` |

---

## 13. Credits

**Team:**

| Name | Role |
|---|---|
| Kunal Pramanik | Source modification, C++ experiments, storage engine analysis |
| Jinal Sasiya | Python experiments, chart generation, write-up |

**Guide:** Prof. Ankush Chander — DS614 Big Data Engineering, DAU Gandhinagar

**Acknowledgments:**
- The DuckDB team at CWI Amsterdam and contributors at [github.com/duckdb/duckdb](https://github.com/duckdb/duckdb) — for building and maintaining an exceptionally well-documented open-source system
- Course instructor, DS614 — for the reverse-engineering methodology that shaped this project

---

*Last Updated: May 2026 · DS614 — Big Data Engineering · DAU Gandhinagar*
