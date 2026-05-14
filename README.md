# 🦆 DuckDB – Columnar Storage Engine Analysis
## Advanced Database Systems Final Project

**Project Title:** *Impact of Physical Block Size on DuckDB Storage Internals*  
**Team Members:** Kunal Pramanik & Jinal Sasiya  
**Database Engine:** DuckDB v0.0.1 (Custom Fork)

---

# 📌 Abstract

DuckDB is a modern analytical database optimized for vectorized execution and high-performance columnar storage. By default, DuckDB uses **256KB physical storage blocks** to maximize sequential I/O, cache locality, and metadata efficiency.

In this project, we intentionally modified DuckDB’s storage engine to use **4KB blocks instead of 256KB blocks** (a 64× reduction) in order to study:

- Storage fragmentation
- Vectorized execution behavior
- WAL overhead
- Metadata pressure
- Cache locality
- BufferManager performance
- Row Group stability

The goal was to understand how low-level storage design impacts the performance and architecture of analytical databases.

---

#  Research Objective

> Analyze the impact of reducing DuckDB’s physical block size from 256KB to 4KB and observe how it affects performance, storage management, vectorized execution, and metadata handling.

---

#  Important Background Concepts

##  Physical Blocks

Physical blocks are the smallest storage units managed by the database on disk.

Default DuckDB block size:

```cpp
#define STORAGE_BLOCK_SIZE (1024 * 256)
```

Equivalent to:

```text
256KB
```

We modified it to:

```cpp
#define STORAGE_BLOCK_SIZE (4096)
```

Equivalent to:

```text
4KB
```

---

##  Row Groups

DuckDB internally organizes data into:

```text
Row Groups
```

Each Row Group contains:

```text
122,880 rows
```

Row Groups preserve logical organization even if physical storage changes.

---

##  Vectorized Execution

DuckDB processes data using vectors instead of row-by-row execution.

Typical vector size:

```text
2048 elements ≈ 16KB
```

Problem:

```text
16KB vectors inside 4KB blocks
```

Meaning:

```text
1 vector spans across 4 physical blocks
```

This causes fragmentation and cache locality issues.

---

#  Modified Architecture

##  Modified Write Path

```text
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
BlockManager::CreateBlock()
   ↓
CheckpointManager / WAL
   ↓
Flush to .duckdb file
```

---

#  Core Modification

Modified file:

```text
src/include/duckdb/storage/storage_info.hpp
```

### Original

```cpp
#define STORAGE_BLOCK_SIZE (1024 * 256)
```

### Modified

```cpp
#define STORAGE_BLOCK_SIZE (4096)
```

This reduced block size by:

```text
64×
```

---

#  Experimental Framework

We performed **10 experiments** to analyze the effect of fragmentation on DuckDB.

| Experiment | Focus Area |
|---|---|
| Experiment 1 | Sequential Scan Performance |
| Experiment 2 | WAL Growth Analysis |
| Experiment 3 | Row Group Fill Density |
| Experiment 4 | VACUUM Stability |
| Experiment 5 | Self-Join Stress Test |
| Experiment 6 | Vector Alignment Analysis |
| Experiment 7 | BufferManager Pressure |
| Experiment 8 | Cache Locality Analysis |
| Experiment 9 | Fragmented Insert Workload |
| Experiment 10 | Checkpoint Flush Analysis |

---

#  Experiment 1 – Sequential Scan Performance

##  Target

Measure analytical query slowdown caused by fragmented blocks.

## Query

```sql
SELECT SUM(val) FROM perf_test;
```

##  Results

| Configuration | Time |
|---|---|
| 256KB Blocks | 0.025s |
| 4KB Blocks | 0.030s |

##  Analysis

Smaller blocks increased:

- Metadata traversal
- Pointer chasing
- Cache misses
- BufferManager overhead

##  Insight

Large blocks are critical for analytical scan efficiency.

---

#  Experiment 2 – WAL Growth Analysis

##  Target

Analyze WAL overhead under fragmentation.

##  Result

The `.wal` file grew much faster in the 4KB version.

##  Analysis

Smaller blocks created:

- More page transitions
- More metadata markers
- More fragmented writes

##  Insight

Fragmentation increases transactional logging overhead significantly.

---

#  Experiment 3 – Row Group Fill Density

##  Target

Check whether Row Groups fragment under 4KB blocks.

##  Result

Both versions showed:

```text
12.288% fill density
```

##  Analysis

```text
122,880 / 1,000,000 = 12.288%
```

Row Groups remained unchanged.

##  Insight

Row Groups are hard architectural invariants in DuckDB.

---

#  Experiment 4 – VACUUM Stability Test

##  Target

Analyze storage reclamation after deletion.

##  Result

Even after deleting 90% rows:

```text
File size remained 18.2MB
```

##  Analysis

DuckDB cannot truncate blocks if even one row remains.

##  Insight

This behavior causes sparse block pinning.

---

#  Experiment 5 – Self-Join Stress Test

##  Target

Stress metadata management and BufferManager.

##  Result

Execution time increased dramatically.

##  Analysis

The engine repeatedly performed:

- Pin/unpin operations
- Metadata traversal
- Fragmented page tracking

##  Insight

Metadata overhead can become larger than actual computation.

---

#  Experiment 6 – Vector Alignment Analysis

##  Target

Analyze vector-block mismatch.

##  Result

Vectors became fragmented across multiple blocks.

##  Analysis

```text
16KB vectors → 4KB blocks
```

Result:

```text
1 vector → 4 blocks
```

##  Insight

Cache locality breaks when vectors no longer align with blocks.

---

#  Experiment 7 – BufferManager Pressure Test

##  Target

Measure BufferManager overhead.

##  Result

Pin/unpin operations increased heavily.

##  Analysis

Tiny blocks forced the BufferManager to manage many more pages.

##  Insight

Fragmentation increases memory-management cost.

---

#  Experiment 8 – Cache Locality Analysis

##  Target

Study CPU cache behavior.

##  Result

4KB storage showed significantly worse cache locality.

##  Analysis

Fragmented blocks forced scattered memory access.

##  Insight

Analytical databases heavily depend on contiguous memory access.

---

#  Experiment 9 – Fragmented Insert Workload

##  Target

Analyze insertion overhead under fragmentation.

##  Result

Insert operations generated highly fragmented writes.

##  Analysis

Small blocks increased:

- WAL markers
- Metadata references
- Write boundaries

##  Insight

Fragmentation amplifies write overhead.

---

#  Experiment 10 – Checkpoint Flush Analysis

##  Target

Analyze checkpoint flushing behavior.

##  Result

Checkpoint flushing became metadata-heavy.

##  Analysis

CheckpointManager had to track many fragmented pages.

##  Insight

Fragmented storage increases checkpoint complexity.

---

#  Failure Analysis

| Failure Case | Related Experiment |
|---|---|
| Metadata Thrashing | Experiment 5 |
| Vector Alignment Mismatch | Experiment 6 |
| BufferManager Pressure | Experiment 7 |
| Cache Locality Breakdown | Experiment 8 |
| Fragmented Write Amplification | Experiment 9 |
| Checkpoint Metadata Explosion | Experiment 10 |

---

#  Failure Case 1 – Metadata Thrashing

### Related Experiment

```text
Experiment 5 – Self-Join Stress Test
```

### Root Cause

The BufferManager had to manage:

- 64× more blocks
- Frequent metadata traversal
- Excessive pin/unpin operations

---

#  Failure Case 2 – Vector Alignment Mismatch

### Related Experiment

```text
Experiment 6 – Vector Alignment Analysis
```

### Root Cause

```text
16KB vectors inside 4KB blocks
```

destroyed cache locality.

---

#  Failure Case 3 – BufferManager Pressure

### Related Experiment

```text
Experiment 7 – BufferManager Pressure Test
```

### Root Cause

Tiny blocks increased memory-management overhead.

---

#  Failure Case 4 – Cache Locality Breakdown

### Related Experiment

```text
Experiment 8 – Cache Locality Analysis
```

### Root Cause

Fragmented blocks forced scattered memory access.

---

#  Failure Case 5 – Fragmented Write Amplification

### Related Experiment

```text
Experiment 9 – Fragmented Insert Workload
```

### Root Cause

More fragmented writes increased WAL and metadata overhead.

---

#  Failure Case 6 – Checkpoint Metadata Explosion

### Related Experiment

```text
Experiment 10 – Checkpoint Flush Analysis
```

### Root Cause

Checkpoint flushing required tracking many fragmented pages.

---

#  Major Findings

##  Finding 1 – Abstraction Layers Work

DuckDB successfully isolated:

```text
Logical execution
```

from:

```text
Physical fragmentation
```

---

##  Finding 2 – Physical Grain Matters

Performance dropped:

```text
0.025s → 0.030s
```

showing that:

> 256KB is a carefully optimized sweet spot.

---

##  Finding 3 – Metadata is the Hidden Bottleneck

Fragmentation wastes:

- CPU cycles
- Cache bandwidth
- Metadata traversal time
- BufferManager resources

---

#  Final Conclusion

Even after reducing physical block size by:

```text
64×
```

DuckDB continued functioning because:

- Row Groups preserved logical organization
- Vectorized execution still worked
- Storage abstraction layers protected the engine

However, fragmentation significantly harmed:

- Cache locality
- WAL efficiency
- Metadata handling
- BufferManager performance
- Sequential throughput

This project proves that analytical database performance depends heavily on:

- Storage layout
- Metadata organization
- Vector alignment
- Cache behavior
- Physical I/O structure

---

#  How to Run the Modified Engine

## Compilation

```powershell
.\out\build\x64-Release\duckdb.exe modified_wal.db
```

---

## Performance Experiment

```sql
.timer on

CREATE TABLE perf_test AS
SELECT range AS val
FROM range(1000000);

CHECKPOINT;

SELECT SUM(val) FROM perf_test;
```

---

## Metadata Experiment

```sql
SELECT segment_type, count(*)
FROM pragma_storage_info('perf_test')
GROUP BY segment_type;
```

---

#  References

1. Raasveldt, M., & Mühleisen, H. (2019). *DuckDB: An Embeddable Analytical Database.*

2. DuckDB Source Code Analysis

```text
src/storage/
```

3. MSVC 2022 Documentation

4. DuckDB Internal Storage Documentation

---

