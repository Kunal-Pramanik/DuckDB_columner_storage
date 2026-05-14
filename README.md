# 🦆 DuckDB – Columnar Storage Engine Analysis


**Course:** DS614 — Big Data Engineering

**Topic:** DuckDB – Columnar Storage Engine Analysis
 
**Approach:** Systems-level reverse engineering using actual DuckDB C++ source code, physical storage block modification experiments, vectorized execution analysis, and fragmentation failure simulation

---

## 📌 Abstract

DuckDB is a modern in-process analytical database optimized for vectorized execution and high-performance columnar storage. By default, DuckDB uses **256 KB physical storage blocks** to maximize sequential I/O, cache locality, and metadata efficiency.

In this project, we intentionally modified DuckDB's storage engine to use **4 KB blocks instead of 256 KB blocks** — a 64× reduction — to study what happens when that fundamental assumption is violated. We observed the effects across 10 experiments spanning storage fragmentation, vectorized execution alignment, WAL overhead, metadata pressure, cache locality, and BufferManager behavior.

> The goal was not to break DuckDB — it was to understand *why* those design choices exist by seeing what changes when they're removed.

---

## 🎯 Research Objective

> Analyze the impact of reducing DuckDB's physical block size from **256 KB to 4 KB** and observe how it propagates through performance, storage management, vectorized execution, and metadata handling.

---

## 📂 Repository Structure

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
├── experiments .py                  # All 6 Python experiments with charts
├── DuckDB_Columnar_Storage.pptx     # Presentation deck
└── README.md
```

---

## 🔧 Core Modification

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

## 📚 Important Background Concepts

### Physical Blocks

Physical blocks are the smallest storage units that the database engine reads from and writes to disk. DuckDB's default 256 KB block size is carefully tuned to:

- Match typical OS page cache behavior
- Minimize metadata-per-byte ratio
- Align with SSDs' optimal sequential write unit
- Fit comfortably in L2/L3 CPU cache during scans

### Row Groups

DuckDB internally organizes columnar data into **Row Groups**, each containing exactly 122,880 rows. Row Groups are the logical unit of statistics, compression, and parallel execution. Importantly, Row Groups exist above the physical block layer — changing block size does not change Row Group boundaries.

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

## 🏗️ Modified Write Path

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

---

## 🧪 Experimental Framework

We ran **10 experiments** to systematically cover every layer the block size change touches.

| # | Experiment | Focus Area |
|---|-----------|------------|
| 1 | Sequential Scan Performance | Query throughput on full scans |
| 2 | WAL Growth Analysis | Write-ahead log overhead |
| 3 | Row Group Fill Density | Logical organization stability |
| 4 | VACUUM Stability Test | Storage reclamation after deletes |
| 5 | Self-Join Stress Test | Metadata management under joins |
| 6 | Vector Alignment Analysis | Cache impact of vector-block mismatch |
| 7 | BufferManager Pressure Test | Pin/unpin overhead |
| 8 | Cache Locality Analysis | CPU cache behavior |
| 9 | Fragmented Insert Workload | Write amplification |
| 10 | Checkpoint Flush Analysis | Checkpoint complexity |

---

## 📊 Experiment Results

---

### Experiment 1 — Sequential Scan Performance

**Target:** Measure analytical query slowdown caused by fragmented blocks.

**Query run:**
```sql
SELECT SUM(val) FROM perf_test;
```

**Results:**

| Configuration | Time |
|---------------|------|
| 256 KB Blocks | 0.025s |
| 4 KB Blocks   | 0.030s |

**Analysis:** Smaller blocks force more metadata traversal — each physical read requires a block header lookup, a pointer dereference into the BufferManager, and a page pin. With 256 KB blocks, a 1 million-row column scan touches ~4 blocks. With 4 KB blocks, the same scan touches ~250 blocks. This multiplies cache misses and BufferManager overhead.

**Insight:** Large blocks are critical for analytical scan efficiency. The 256 KB default is not arbitrary — it matches the typical size at which sequential I/O amortizes metadata cost.

---

### Experiment 2 — WAL Growth Analysis

**Target:** Analyze how fragmentation inflates write-ahead log overhead.

**Result:** The `.wal` file grew significantly faster with 4 KB blocks.

**Analysis:** Each block boundary generates a WAL marker. With 64× more blocks, the WAL must record 64× more page transitions, metadata entries, and fragmented write boundaries per data insert. For transactional workloads, this means proportionally more I/O on recovery paths and during checkpointing.

**Insight:** Fragmentation is not just a read-time problem — it directly amplifies transactional write overhead.

---

### Experiment 3 — Row Group Fill Density

**Target:** Verify whether Row Groups fragment when physical blocks change.

**Result:** Both configurations showed identical fill density:

```
122,880 / 1,000,000 = 12.288%
```

**Analysis:** Row Groups are a *logical* abstraction maintained above the physical storage layer. `RowGroupCollection` and `ColumnData` do not change their row-grouping behavior based on `STORAGE_BLOCK_SIZE`. The logical organization is preserved even when the physical substrate is fragmented.

**Insight:** DuckDB's architectural separation between logical Row Groups and physical blocks is robust. This is a deliberate design — the optimizer and statistics layer can remain stable across storage configurations.

---

### Experiment 4 — VACUUM Stability Test

**Target:** Analyze storage reclamation after mass deletion.

**Procedure:** Inserted 1M rows, deleted 90%.

**Result:** Even after deleting 90% of rows, file size remained at **18.2 MB**.

**Analysis:** DuckDB cannot truncate a physical block if even one row within it is still live. With 4 KB blocks, deleted rows are distributed more thinly across more blocks — meaning more blocks remain "pinned" by a single survivor row. This is called *sparse block pinning* and is worse under small block sizes.

**Insight:** This is the physical manifestation of the row group tombstone problem. Production systems need compaction/rewrite passes (equivalent to VACUUM FULL in PostgreSQL) to reclaim space.

---

### Experiment 5 — Self-Join Stress Test

**Target:** Stress metadata management and BufferManager under complex query patterns.

**Result:** Execution time increased dramatically with 4 KB blocks.

**Analysis:** A self-join requires the engine to scan the same column data multiple times while maintaining join state. With 4 KB blocks, each re-scan hits the BufferManager more times, triggers more pin/unpin cycles, and evicts more entries from the buffer pool. Metadata traversal cost becomes larger than the actual computation.

**Insight:** For complex queries, metadata overhead can dominate. This is why DuckDB's BufferManager is designed around large blocks — the ratio of metadata cost to data processed must remain small.

---

### Experiment 6 — Vector Alignment Analysis

**Target:** Analyze the cache impact when vectors no longer align with blocks.

**Calculation:**

```
Default vector size: 2048 × 8 bytes (double) = 16 KB
4 KB block size → 1 vector spans 4 physical blocks
```

**Result:** Vectorized operations that previously processed data entirely within one block now cross block boundaries, requiring multiple buffer pool lookups per vector.

**Analysis:** DuckDB's SIMD and auto-vectorization depend on data being contiguous in memory. When a vector crosses a block boundary, the engine cannot guarantee memory contiguity without an intermediate copy step, destroying cache line efficiency.

**Insight:** The 256 KB block size was chosen partly to ensure that multiple vectors fit inside a single block, eliminating cross-boundary fragmentation entirely.

---

### Experiment 7 — BufferManager Pressure Test

**Target:** Measure how much additional overhead the BufferManager carries under fragmentation.

**Result:** Pin/unpin operations increased proportionally to the block count increase (approximately 64×).

**Analysis:** The BufferManager maintains a fixed-size pool of pinned blocks. With 64× more blocks for the same data, the pool fills up faster, eviction runs more frequently, and the LRU clock cycles more aggressively — even for queries that were previously well within the buffer budget.

**Insight:** BufferManager pressure is not just about memory — frequent eviction also burns CPU cycles. Fragmented storage creates a hidden CPU tax.

---

### Experiment 8 — Cache Locality Analysis

**Target:** Measure CPU cache behavior during scans.

**Result:** 4 KB block storage showed significantly worse cache hit rates.

**Analysis:** When data from a single column is scattered across 64× more block headers and metadata structures, the CPU cache must hold all of that metadata simultaneously to execute a scan. This crowds out the actual column data from L1/L2 cache, causing thrashing.

**Insight:** Analytical databases rely on the "streaming" memory access pattern — reading one column sequentially so the hardware prefetcher can run ahead. Fragmentation breaks this pattern.

---

### Experiment 9 — Fragmented Insert Workload

**Target:** Measure write amplification under fragmented block sizes.

**Result:** Insert operations generated significantly more fragmented writes — each batch touched more blocks, wrote more WAL entries, and updated more metadata structures.

**Analysis:** For bulk INSERT operations, 4 KB blocks create more write boundaries. A 1 MB insert that fills ~4 blocks at 256 KB generates 256 blocks at 4 KB — 256 block headers, 256 WAL markers, 256 BufferManager registrations.

**Insight:** Columnar stores are designed for bulk inserts, not row-by-row. Even under batch inserts, fragmentation amplifies every write by the block-count multiplier.

---

### Experiment 10 — Checkpoint Flush Analysis

**Target:** Analyze how checkpoint flushing behaves under fragmentation.

**Result:** Checkpoint flushing became metadata-heavy — `CheckpointManager` had to serialize and flush significantly more block descriptors, requiring more I/O and longer checkpoint pauses.

**Analysis:** DuckDB's `CheckpointManager` iterates over all dirty blocks and flushes them to the `.duckdb` file. With 4 KB blocks, "all dirty blocks" means 64× more entries to iterate, 64× more fsync-able units, and 64× more footer metadata to write.

**Insight:** In production, checkpoint pause time directly impacts query latency. Fragmentation turns a fast checkpoint into a long one.

---

## 🔴 Failure Analysis

| Failure Case | Root Cause | Related Experiment |
|---|---|---|
| Metadata Thrashing | 64× more blocks → 64× more pin/unpin cycles | Experiment 5 |
| Vector Alignment Mismatch | 16 KB vectors split across 4 KB blocks | Experiment 6 |
| BufferManager Pressure | Pool eviction rate exceeded sustainable threshold | Experiment 7 |
| Cache Locality Breakdown | Column data crowded out of cache by metadata | Experiment 8 |
| Fragmented Write Amplification | Each insert boundary multiplied 64× | Experiment 9 |
| Checkpoint Metadata Explosion | Checkpoint must enumerate all 64× blocks | Experiment 10 |

---

### Failure Case 1 — Metadata Thrashing

**Related:** Experiment 5 — Self-Join Stress Test

**Root Cause:**
The BufferManager had to track 64× more live blocks for the same data. Every time a query needed to reference a block during join processing, it had to:
1. Look up the block ID in the buffer pool
2. Increment a pin counter
3. Decrement the pin counter on completion

With 64× more blocks, this three-step process ran 64× more often per query, making metadata management dominate execution time.

---

### Failure Case 2 — Vector Alignment Mismatch

**Related:** Experiment 6 — Vector Alignment Analysis

**Root Cause:**
```
16 KB vectors inside 4 KB blocks
→ 1 vector = 4 physical blocks
→ vectorized operations lose contiguity guarantees
```

DuckDB's vectorized engine assumes that a vector of 2048 elements lives in contiguous memory. When that vector crosses block boundaries, the engine must either:
- Copy data into a temporary contiguous buffer (extra allocation + copy cost), or
- Process sub-vectors per block (breaking SIMD pipeline efficiency)

---

### Failure Case 3 — BufferManager Pressure

**Related:** Experiment 7 — BufferManager Pressure Test

**Root Cause:** The fixed buffer pool filled with 64× more block entries. The eviction algorithm (LRU clock) ran nearly continuously, evicting blocks that were needed moments later — a classic thrashing pattern.

---

### Failure Case 4 — Cache Locality Breakdown

**Related:** Experiment 8 — Cache Locality Analysis

**Root Cause:** Each 4 KB block carries its own header (block ID, reference count, dirty flag, next-block pointer). At 256 KB, this header overhead is negligible relative to data. At 4 KB, the header represents a larger fraction of each block, and 64× more headers must live in cache simultaneously during a scan.

---

### Failure Case 5 — Fragmented Write Amplification

**Related:** Experiment 9 — Fragmented Insert Workload

**Root Cause:** DuckDB writes data to blocks sequentially. With 4 KB blocks, every 4 KB of new data creates a new block descriptor, a new WAL entry, and a new BufferManager registration. For a 100 MB batch insert, the 256 KB configuration creates ~400 blocks; the 4 KB configuration creates ~25,600.

---

### Failure Case 6 — Checkpoint Metadata Explosion

**Related:** Experiment 10 — Checkpoint Flush Analysis

**Root Cause:** `CheckpointManager::WriteData()` iterates the entire list of dirty blocks. With 64× more blocks, this iteration itself becomes expensive. Each block must be flushed and its descriptor written to the checkpoint footer — making the footer 64× larger and the flush process 64× slower.

---

## 💡 Major Findings

### Finding 1 — DuckDB's Abstraction Layers Are Robust

Despite the 64× block size reduction, DuckDB continued functioning correctly for all queries. Row Groups preserved logical organization, vectorized execution produced correct results, and the SQL interface behaved identically. The abstraction between logical and physical storage is genuine — not just theoretical.

### Finding 2 — 256 KB Is a Carefully Optimized Sweet Point

Performance degraded measurably (0.025s → 0.030s for simple scans) even at small scale. At analytical-scale datasets (billions of rows), this ~20% overhead compounds severely. The 256 KB default represents years of empirical tuning against real hardware characteristics.

> The block size is not a configuration knob you tune per workload — it is a fundamental constant that must be co-designed with the rest of the storage engine.

### Finding 3 — Metadata Is the Hidden Bottleneck

All six failure cases trace back to the same root cause: more blocks means more metadata. In analytical databases, the *ratio of metadata cost to data processed* must remain small. Any design that increases this ratio — whether through small blocks, excessive indexing, or fine-grained locking — degrades performance in ways that are difficult to diagnose from query execution plans alone.

---

## ✅ Final Conclusion

Even after reducing physical block size by **64×**, DuckDB remained functionally correct because:

- Row Groups are a logical invariant above the physical layer
- Vectorized execution adapts to block boundaries (at a cost)
- Storage abstraction layers protect query semantics

However, fragmentation **measurably harmed**:

- Sequential scan throughput
- WAL efficiency and checkpoint pause time
- BufferManager utilization
- CPU cache hit rates
- Write amplification ratio

This project confirms that analytical database performance is not just about algorithms or query plans. It depends fundamentally on:

- **Storage layout** — contiguous column data minimizes I/O
- **Block granularity** — must be co-designed with vector size and cache size
- **Metadata organization** — overhead must remain proportionally small
- **Physical I/O structure** — large sequential reads beat small random reads

The 256 KB block is not a magic number. It is the result of balancing all of these constraints simultaneously on modern hardware.

---

## 🚀 How to Run

### Build the Modified Engine (Windows, MSVC 2022)

```bat
cd duckdb
cmake -S . -B out/build/x64-Release -G "Visual Studio 17 2022" -A x64
cmake --build out/build/x64-Release --config Release
```

### Launch the Modified DuckDB Shell

```bat
.\out\build\x64-Release\duckdb.exe modified_wal.db
```

### Run Performance Experiment (inside DuckDB shell)

```sql
.timer on

CREATE TABLE perf_test AS
SELECT range AS val FROM range(1000000);

CHECKPOINT;

SELECT SUM(val) FROM perf_test;
```

### Run Metadata Inspection

```sql
SELECT segment_type, count(*)
FROM pragma_storage_info('perf_test')
GROUP BY segment_type;
```

### Run Python Experiments

```bash
pip install duckdb pandas numpy matplotlib
python "experiments .py"
```

Charts will be saved to `./charts/`.

---

## 🐍 Python Experiments Summary

`experiments .py` contains **6 Python-level experiments** using DuckDB's Python API to study performance from the query layer:

| Experiment | What It Measures | Chart |
|---|---|---|
| Exp 1 | Column scan vs full row scan (10M rows) | `exp1_column_scan.png` |
| Exp 2 | Compression ratios by data distribution | `exp2_compression.png` |
| Exp 3 | Query time vs dataset size (100K–25M rows) | `exp3_scalability.png` |
| Exp 4 | GROUP BY under uniform vs skewed data | `exp4_skew.png` |
| Exp 5 | INSERT performance by batch size | `exp5_write.png` |
| Exp 6 | EXPLAIN ANALYZE — physical query plan | *(stdout)* |

Key result from Exp 1 (10M rows):

| Query | Time |
|-------|------|
| `SELECT * LIMIT 500000` (5 columns) | slowest |
| `SELECT AVG(salary)` (1 column) | ~4× faster |
| `SELECT COUNT(*)` (no data) | ~8× faster |

This directly demonstrates DuckDB's columnar advantage — reading fewer columns means reading fewer bytes, regardless of how many columns the table has.

---

## 📋 Source Files We Modified / Analyzed

| File | Purpose |
|---|---|
| `src/include/duckdb/storage/storage_info.hpp` | Block size constant — our core modification |
| `src/storage/buffer/buffer_manager.cpp` | Pin/unpin logic, pool eviction |
| `src/storage/checkpoint/write_overflow_strings_to_disk.cpp` | Checkpoint serialization |
| `src/storage/column_data.cpp` | Column append path |
| `src/storage/table/row_group.cpp` | Row Group management |
| `src/transaction/wal_write_state.cpp` | WAL entry generation |

---

## 📖 References

1. Raasveldt, M., & Mühleisen, H. (2019). *DuckDB: An Embeddable Analytical Database*. SIGMOD.
2. DuckDB Source Code — `src/storage/` directory
3. Abadi, D., et al. (2008). *Column Stores vs. Row Stores: How Different Are They Really?* SIGMOD.
4. Boncz, P., et al. (2005). *MonetDB/X100: Hyper-Pipelining Query Execution*. CIDR.
5. MSVC 2022 Documentation — CMake integration for C++ projects

---

## 👥 Team

| Name | Role |
|------|------|
| Kunal Pramanik | Source modification, C++ experiments, analysis |
| Jinal Sasiya | Python experiments, chart generation, write-up |

---

*DS614 — Big Data Engineering*
