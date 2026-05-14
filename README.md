# **DuckDB Storage Engine: Architectural Analysis & Block Size Modification**

**Author:** Kunal Pramanik  
**Program:** MSc Data Science (Semester 2)  
**Academic Year:** 2025–2026  
**Project Focus:** Database Internals, C++ Systems Engineering, and Storage Layer Optimization

---

## **1. Project Overview & Objectives**
The goal of this project was to reverse-engineer and stress-test the **DuckDB Storage Engine** by artificially shrinking the physical storage grain. I modified the core C++ source code to reduce the `STORAGE_BLOCK_SIZE` from the default **256KB** down to **4KB**—a 64x reduction. This allowed for a granular analysis of the trade-offs between storage density, metadata overhead, and analytical performance.

### **Key Technical Targets**
*   **Source Modification:** Altering physical constants in the storage header (`storage_info.hpp`).
*   **System Tracing:** Following the "Write Path" from high-level SQL operators down to the Block Manager.
*   **Performance Benchmarking:** Quantifying the impact of block fragmentation on vectorized execution.

---

## **2. Environment Setup & Compiler Patching**
To build the engine in a modern Windows environment (Visual Studio 2022), I implemented a critical patch to resolve environmental conflicts:
*   **Target:** `src/common/exception.cpp`.
*   **Issue:** `stdext` namespace conflicts with modern MSVC standards.
*   **Fix:** Updated namespace references to ensure a successful compilation of the `x64-Release` binary.

---

## **3. The 10-Experiment Deep Dive**

| # | Experiment | Target | Observed Result |
| :--- | :--- | :--- | :--- |
| 1 | **Block Size Static Analysis** | `storage_info.hpp` | Both versions measured 2.01 MB; compression masked the block change. |
| 2 | **WAL Pressure Test** | `write_ahead_log.cpp` | Immediate bloat in the 4KB version's `.wal` file. |
| 3 | **High Entropy Stress** | UUID Data | File sizes increased to 13.2 MB; random data bypasses compression. |
| 4 | **Scan Performance** | `SUM(val)` | **20% Time Penalty** (0.030s vs 0.025s) due to cache misses. |
| 5 | **Row Group Sovereignty** | `pragma_storage_info` | Constant 12.288% fill density; row groups override block limits. |
| 6 | **Dictionary Stress** | `dictionary_compression.cpp`| Fallback to Flat String compression due to insufficient block space. |
| 7 | **Internal Fragmentation** | Metadata Mapping | Modified version covered smaller row ranges per segment "hop". |
| 8 | **Vacuum Stability** | `DELETE` + `VACUUM` | File size remained at 18.2 MB; blocks could not be truncated. |
| 9 | **Join Thrashing** | `JOIN` Performance | Operation became **computationally infeasible** (system timeout). |
| 10 | **Metadata Resilience** | Final Segment Count | Consolidated into 2 segments; logical layer hides physical flaws. |

---

## **4. Failure Case Analysis**
This section details the specific scenarios where the 4KB block size modification caused the system to perform significantly below baseline or fail to meet architectural expectations.

### **Category A: Performance & Computational Failures**
*   **Experiment 9 (Join Thrashing):** This was the most catastrophic failure. Joining 1,000,000 rows required the `BufferManager` to "pin" and "unpin" 64x more blocks than the baseline. The metadata overhead for tracking these tiny blocks overwhelmed the CPU, making the query effectively infinite.
*   **Experiment 4 (Scan Performance Penalty):** A 20% slowdown (0.005s difference) was observed during simple aggregations. This failure is attributed to **CPU Cache Misses**; because data is fragmented across 4KB blocks, the CPU cannot perform long sequential pre-fetches into the L1/L2 cache.

### **Category B: Storage Efficiency Failures**
*   **Experiment 6 (Dictionary Degradation):** In the baseline, DuckDB uses efficient Dictionary Encoding for strings. In the 4KB version, the engine "gave up" on building dictionaries because the physical blocks were too small to hold a meaningful symbol table. This forced a fallback to expensive **Flat String** storage.
*   **Experiment 8 (Vacuum/Truncation Failure):** After deleting 90% of the table rows, the file size failed to shrink. This is a **Persistence Failure** caused by "Sparse Block Pinning." Because the remaining 10% of data was scattered across 4KB blocks, the `BlockManager` could not find contiguous empty space to truncate the file.

### **Category C: I/O & Metadata Failures**
*   **Experiment 2 (WAL Pressure):** The Write-Ahead Log experienced massive bloat. Every tiny page transition triggered a log record, creating an I/O bottleneck that would lead to significant recovery delays after a system crash.
*   **Experiment 7 (Internal Metadata Fragmentation):** The metadata index required 64x more entries to map the same number of rows. This increases the memory footprint of the `StorageManager` and slows down every subsequent metadata lookup.

---

## **5. Final Technical Summary**
| Concept | Modification | Impact Observed |
| :--- | :--- | :--- |
| **Storage Grain** | 256KB $\rightarrow$ 4KB | **20% slower** scan speed; system timeout on joins. |
| **Write Integrity** | No Checkpoint | **WAL Bloat** and page transition fragmentation. |
| **Vectorization** | Vector > Block | Increased **Buffer Cache** pressure and pinning overhead. |
| **Metadata** | `pragma_storage` | High **Row Group** resilience against physical hacks. |

---

### **How to Deploy**
1.  **Clone** this repository to your local drive.
2.  **Compile** using the `x64-Release` profile in Visual Studio 2022.
3.  **Execute:**
    ```powershell
    .\out\build\x64-Release\duckdb.exe modified_wal.db
    ```
