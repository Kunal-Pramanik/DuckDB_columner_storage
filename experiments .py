"""
DuckDB – Columnar Storage Project
Experiments & Analysis Code
Group: Data Riders | Kunal Pramanik & Jinal Sasiya
"""

import duckdb
import time
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ─────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────

os.makedirs("charts", exist_ok=True)

SEPARATOR = "\n" + "=" * 65 + "\n"

def print_header(title):
    print(SEPARATOR)
    print(f"  🦆 {title}")
    print(SEPARATOR)

def timer(label, fn):
    """Run fn(), print elapsed time with a label, return elapsed."""
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    print(f"   ⏱  {label:<45} {elapsed:.4f}s")
    return elapsed, result


# ─────────────────────────────────────────────────────────────────
# EXPERIMENT 1: Columnar Advantage — Single Column vs Full Scan
# ─────────────────────────────────────────────────────────────────

def experiment_1_column_vs_row_scan():
    print_header("Experiment 1 — Columnar Advantage: Single Column vs Full Scan")

    n = 10_000_000
    print(f"  Generating {n:,} rows × 5 columns...")
    np.random.seed(42)
    df = pd.DataFrame({
        "id":         np.arange(n),
        "name":       np.random.choice(["Alice", "Bob", "Charlie", "Diana", "Eve"], n),
        "salary":     np.random.randint(30_000, 200_000, n),
        "department": np.random.choice(["HR", "Eng", "Sales", "Finance"], n),
        "age":        np.random.randint(22, 65, n),
    })

    con = duckdb.connect()
    con.execute("CREATE TABLE employees AS SELECT * FROM df")
    print("  Table created.\n")

    queries = [
        ("SELECT * LIMIT 500000 (all 5 columns)",    "SELECT * FROM employees LIMIT 500000"),
        ("SELECT AVG(salary) (1 column only)",        "SELECT AVG(salary) FROM employees"),
        ("SELECT dept, AVG(salary) GROUP BY dept",    "SELECT department, AVG(salary) FROM employees GROUP BY department"),
        ("SELECT COUNT(*) (no data read)",            "SELECT COUNT(*) FROM employees"),
        ("SELECT id, salary WHERE salary > 100000",   "SELECT id, salary FROM employees WHERE salary > 100000"),
    ]

    labels, times = [], []
    for label, sql in queries:
        t, _ = timer(label, lambda q=sql: con.execute(q).fetchall())
        labels.append(label.split("(")[0].strip())
        times.append(t)

    # Plot
    colors = ["#E74C3C", "#27AE60", "#27AE60", "#3498DB", "#3498DB"]
    fig, ax = plt.subplots(figsize=(11, 5))
    bars = ax.barh(labels, times, color=colors, edgecolor="white", height=0.55)
    ax.set_xlabel("Execution Time (seconds)", fontsize=12)
    ax.set_title("DuckDB: Column Scan vs Full Row Scan\n10 Million Rows", fontsize=13, fontweight="bold")
    ax.bar_label(bars, fmt="%.3fs", padding=4, fontsize=9)
    ax.invert_yaxis()
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(0, max(times) * 1.3)

    red_patch = mpatches.Patch(color="#E74C3C", label="Full scan (slow)")
    green_patch = mpatches.Patch(color="#27AE60", label="Column-selective (fast)")
    ax.legend(handles=[red_patch, green_patch], loc="lower right", fontsize=9)
    plt.tight_layout()
    plt.savefig("charts/exp1_column_scan.png", dpi=150)
    plt.close()
    print("\n  ✅ Chart saved → charts/exp1_column_scan.png")
    con.close()


# ─────────────────────────────────────────────────────────────────
# EXPERIMENT 2: Compression — Low vs High Cardinality
# ─────────────────────────────────────────────────────────────────

def experiment_2_compression():
    print_header("Experiment 2 — Compression: Low vs High Cardinality Data")

    n = 1_000_000
    np.random.seed(42)

    datasets = {
        "Low-cardinality strings\n['A','B','C'] (dictionary encoding)":
            pd.DataFrame({"val": np.random.choice(["A", "B", "C"], n)}),
        "Integer sequence 0..N\n(bitpacking/delta encoding)":
            pd.DataFrame({"val": np.arange(n)}),
        "Repeated integer (all same)\n(RLE encoding)":
            pd.DataFrame({"val": np.full(n, 42)}),
        "Random floats\n(minimal compression)":
            pd.DataFrame({"val": np.random.random(n)}),
        "High-cardinality UUIDs\n(poor compression)":
            pd.DataFrame({"val": [f"user-{i:010d}" for i in range(n)]}),
    }

    results = {}
    for desc, df in datasets.items():
        fname = f"charts/tmp_{desc[:10].replace('/', '_').replace(' ', '_')}.duckdb"
        con = duckdb.connect(fname)
        con.execute("CREATE TABLE data AS SELECT * FROM df")
        # Checkpoint to flush to disk
        con.execute("CHECKPOINT")
        con.close()
        size_mb = os.path.getsize(fname) / 1024 / 1024
        os.remove(fname)
        short = desc.split("\n")[0]
        results[short] = size_mb
        print(f"   {short:<42} {size_mb:.2f} MB")

    # Plot
    labels = list(results.keys())
    sizes  = list(results.values())
    fig, ax = plt.subplots(figsize=(10, 5))
    bar_colors = ["#27AE60", "#27AE60", "#27AE60", "#E67E22", "#E74C3C"]
    bars = ax.bar(range(len(labels)), sizes, color=bar_colors, edgecolor="white", width=0.55)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=15, ha="right", fontsize=9)
    ax.set_ylabel("File Size on Disk (MB)", fontsize=12)
    ax.set_title("DuckDB Compression — 1M Rows, Different Data Distributions", fontsize=12, fontweight="bold")
    ax.bar_label(bars, fmt="%.2f MB", padding=3, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)

    green_p  = mpatches.Patch(color="#27AE60", label="Good compression")
    orange_p = mpatches.Patch(color="#E67E22", label="Moderate")
    red_p    = mpatches.Patch(color="#E74C3C", label="Poor compression")
    ax.legend(handles=[green_p, orange_p, red_p], fontsize=9)
    plt.tight_layout()
    plt.savefig("charts/exp2_compression.png", dpi=150)
    plt.close()
    print("\n  ✅ Chart saved → charts/exp2_compression.png")


# ─────────────────────────────────────────────────────────────────
# EXPERIMENT 3: Scalability — Query Time vs Data Size
# ─────────────────────────────────────────────────────────────────

def experiment_3_scalability():
    print_header("Experiment 3 — Scalability: Query Time vs Data Size")

    sizes = [100_000, 500_000, 1_000_000, 2_500_000, 5_000_000, 10_000_000, 25_000_000]
    avg_times, count_times, filter_times = [], [], []

    con = duckdb.connect()
    np.random.seed(42)

    for n in sizes:
        df = pd.DataFrame({
            "a": np.random.randint(0, 1000, n),
            "b": np.random.random(n),
        })
        con.execute("DROP TABLE IF EXISTS scalability_test")
        con.execute("CREATE TABLE scalability_test AS SELECT * FROM df")

        t1, _ = timer(f"n={n:>10,}  AVG(b)", lambda: con.execute("SELECT AVG(b) FROM scalability_test").fetchall())
        t2, _ = timer(f"n={n:>10,}  COUNT(*)", lambda: con.execute("SELECT COUNT(*) FROM scalability_test").fetchall())
        t3, _ = timer(f"n={n:>10,}  FILTER a<100", lambda: con.execute("SELECT AVG(b) FROM scalability_test WHERE a < 100").fetchall())

        avg_times.append(t1)
        count_times.append(t2)
        filter_times.append(t3)
        print()

    labels = [f"{n/1_000_000:.1f}M" for n in sizes]
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(labels, avg_times,    marker="o", color="#3498DB", label="AVG(b) — full scan",   linewidth=2)
    ax.plot(labels, count_times,  marker="s", color="#27AE60", label="COUNT(*)",              linewidth=2)
    ax.plot(labels, filter_times, marker="^", color="#E74C3C", label="AVG(b) WHERE a<100",    linewidth=2)
    ax.set_xlabel("Number of Rows", fontsize=12)
    ax.set_ylabel("Query Time (seconds)", fontsize=12)
    ax.set_title("DuckDB Scalability — Query Time vs Dataset Size", fontsize=13, fontweight="bold")
    ax.legend(fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig("charts/exp3_scalability.png", dpi=150)
    plt.close()
    print("  ✅ Chart saved → charts/exp3_scalability.png")
    con.close()


# ─────────────────────────────────────────────────────────────────
# EXPERIMENT 4: Data Skew Analysis
# ─────────────────────────────────────────────────────────────────

def experiment_4_data_skew():
    print_header("Experiment 4 — Failure Analysis: Data Skew in GROUP BY")

    n = 2_000_000
    np.random.seed(42)
    con = duckdb.connect()

    # Uniform
    df_uniform = pd.DataFrame({
        "dept":   np.random.choice(["Eng", "HR", "Sales", "Finance"], n),
        "salary": np.random.randint(30_000, 200_000, n),
    })
    con.execute("CREATE TABLE uniform_data AS SELECT * FROM df_uniform")
    t_uni, _ = timer("Uniform GROUP BY (equal distribution)", lambda: con.execute(
        "SELECT dept, AVG(salary), COUNT(*) FROM uniform_data GROUP BY dept").fetchall())

    # Moderately skewed (60/20/10/10)
    df_mod = pd.DataFrame({
        "dept":   np.random.choice(["Eng", "HR", "Sales", "Finance"], n, p=[0.60, 0.20, 0.10, 0.10]),
        "salary": np.random.randint(30_000, 200_000, n),
    })
    con.execute("CREATE TABLE moderate_skew AS SELECT * FROM df_mod")
    t_mod, _ = timer("Moderate skew (60/20/10/10)", lambda: con.execute(
        "SELECT dept, AVG(salary), COUNT(*) FROM moderate_skew GROUP BY dept").fetchall())

    # Highly skewed (90/4/3/3)
    df_skew = pd.DataFrame({
        "dept":   np.random.choice(["Eng", "HR", "Sales", "Finance"], n, p=[0.90, 0.04, 0.03, 0.03]),
        "salary": np.random.randint(30_000, 200_000, n),
    })
    con.execute("CREATE TABLE skewed_data AS SELECT * FROM df_skew")
    t_skew, _ = timer("Highly skewed (90/4/3/3)", lambda: con.execute(
        "SELECT dept, AVG(salary), COUNT(*) FROM skewed_data GROUP BY dept").fetchall())

    # Plot pie charts + bar chart
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    distributions = [
        ("Uniform\n25/25/25/25", [0.25, 0.25, 0.25, 0.25], t_uni),
        ("Moderate Skew\n60/20/10/10", [0.60, 0.20, 0.10, 0.10], t_mod),
        ("High Skew\n90/4/3/3", [0.90, 0.04, 0.03, 0.03], t_skew),
    ]
    colors = ["#3498DB", "#27AE60", "#E74C3C", "#F39C12"]

    for ax, (title, sizes, t) in zip(axes, distributions):
        ax.pie(sizes, labels=["Eng", "HR", "Sales", "Finance"], colors=colors,
               autopct="%1.0f%%", startangle=90, textprops={"fontsize": 10})
        ax.set_title(f"{title}\nQuery time: {t:.4f}s", fontsize=11, fontweight="bold")

    plt.suptitle("DuckDB GROUP BY — Uniform vs Skewed Data (2M rows)", fontsize=13, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig("charts/exp4_skew.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("\n  ✅ Chart saved → charts/exp4_skew.png")
    con.close()


# ─────────────────────────────────────────────────────────────────
# EXPERIMENT 5: Write-Heavy Workload Failure Analysis
# ─────────────────────────────────────────────────────────────────

def experiment_5_write_performance():
    print_header("Experiment 5 — Failure Analysis: Write-Heavy Workload")

    con = duckdb.connect()
    con.execute("CREATE TABLE write_test (id INTEGER, val DOUBLE, name VARCHAR)")

    batch_sizes = [1_000, 10_000, 50_000, 100_000, 500_000]
    insert_rates = []

    for batch in batch_sizes:
        np.random.seed(42)
        df = pd.DataFrame({
            "id":   np.arange(batch),
            "val":  np.random.random(batch),
            "name": np.random.choice(["Alice", "Bob", "Charlie"], batch),
        })
        con.execute("DELETE FROM write_test")

        start = time.perf_counter()
        con.execute("INSERT INTO write_test SELECT * FROM df")
        elapsed = time.perf_counter() - start

        rate = batch / elapsed
        insert_rates.append(rate)
        print(f"   Batch={batch:>8,}  time={elapsed:.4f}s  rate={rate:>12,.0f} rows/sec")

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar([str(b) for b in batch_sizes], [r/1000 for r in insert_rates],
           color="#9B59B6", edgecolor="white", width=0.55)
    ax.set_xlabel("Batch Size (rows)", fontsize=12)
    ax.set_ylabel("Insert Rate (K rows/sec)", fontsize=12)
    ax.set_title("DuckDB Insert Performance by Batch Size\n(Columnar stores are optimized for batch inserts)", fontsize=11, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig("charts/exp5_write.png", dpi=150)
    plt.close()
    print("\n  ✅ Chart saved → charts/exp5_write.png")
    con.close()


# ─────────────────────────────────────────────────────────────────
# EXPERIMENT 6: EXPLAIN ANALYZE — Query Plan Inspection
# ─────────────────────────────────────────────────────────────────

def experiment_6_query_plan():
    print_header("Experiment 6 — Query Plan: EXPLAIN ANALYZE")

    n = 1_000_000
    np.random.seed(42)
    df = pd.DataFrame({
        "dept":   np.random.choice(["Eng", "HR", "Sales", "Finance"], n),
        "salary": np.random.randint(30_000, 200_000, n),
        "age":    np.random.randint(22, 65, n),
    })

    con = duckdb.connect()
    con.execute("CREATE TABLE explain_test AS SELECT * FROM df")

    print("\n  Query 1: SELECT AVG(salary) FROM explain_test")
    plan1 = con.execute("EXPLAIN SELECT AVG(salary) FROM explain_test").fetchall()
    for row in plan1:
        print(row[1])

    print("\n  Query 2: GROUP BY + FILTER")
    plan2 = con.execute("""
        EXPLAIN SELECT dept, AVG(salary)
        FROM explain_test
        WHERE age > 40
        GROUP BY dept
    """).fetchall()
    for row in plan2:
        print(row[1])

    con.close()
    print("\n  ✅ Experiment 6 complete — study the physical plan above")


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🦆 DuckDB — Columnar Storage Project")
    print("   All Experiments | Group: Data Riders")
    print("   Kunal Pramanik & Jinal Sasiya\n")

    experiment_1_column_vs_row_scan()
    experiment_2_compression()
    experiment_3_scalability()
    experiment_4_data_skew()
    experiment_5_write_performance()
    experiment_6_query_plan()

    print(SEPARATOR)
    print("  🎉 All experiments complete!")
    print("  📊 Charts saved in: ./charts/")
    print("  📋 Include these charts in your report and presentation.")
    print(SEPARATOR)
