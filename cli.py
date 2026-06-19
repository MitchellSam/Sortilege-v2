"""
Dev-only dry-run harness for threshold calibration.
Runs the cascade against real files, logs tier/score/destination, moves nothing.
Outputs a CSV for threshold analysis.

Usage:
    python cli.py dry-run --source "C:\\Users\\...\\Downloads" --limit 100
    python cli.py dry-run --source "C:\\Users\\...\\Downloads" --limit 100 --no-api
"""
import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

WORKSPACE_DIR = Path(os.environ.get("SORTILEGE_WORKSPACE", r"C:\sortilege-workspace"))
CONFIG_PATH = WORKSPACE_DIR / "config.json"
DB_PATH = WORKSPACE_DIR / "sortilege.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
RULES_PATH = WORKSPACE_DIR / "rules.yaml"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"Config not found at {CONFIG_PATH}. Run setup first.", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def cmd_dry_run(args) -> None:
    from sortilege.core import registry, cascade
    from sortilege.core.embeddings import load_model
    from sortilege.core.extractor import long_path

    config = load_config()
    output_root = Path(config["output_root"])

    registry.init_db(DB_PATH, SCHEMA_PATH)
    cascade.configure(RULES_PATH)

    print("Loading embedding model...", flush=True)
    load_model()
    print("Model loaded.", flush=True)

    source = Path(args.source)
    if not source.exists():
        print(f"Source path does not exist: {source}", file=sys.stderr)
        sys.exit(1)

    # Collect files
    all_files = []
    for root, _, files in os.walk(long_path(str(source))):
        for fname in files:
            all_files.append(os.path.join(root, fname))
    if args.limit:
        all_files = all_files[: args.limit]

    if args.no_api:
        config = dict(config)
        config["api_cost_ceiling_usd"] = 0.0

    output_csv = Path(args.output) if args.output else source.parent / "dry_run_results.csv"
    fieldnames = [
        "filename", "ext", "size_bytes",
        "tier", "confidence", "proposed_path", "planned_op", "reasoning",
        "is_dupe", "dupe_kind", "elapsed_ms",
    ]

    total = len(all_files)
    print(f"Processing {total} files from {source}")
    print(f"Output: {output_csv}\n")

    counts: dict[str, int] = {str(i): 0 for i in range(6)}
    counts["dupe"] = 0

    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for i, fpath in enumerate(all_files, 1):
            fname = Path(fpath).name
            ext = Path(fpath).suffix.lower().lstrip(".")
            try:
                size = os.path.getsize(fpath)
            except OSError:
                size = 0

            t0 = time.perf_counter()
            try:
                # Create a temporary file row for this dry run
                import hashlib
                sha256 = _hash_file(fpath)

                file_id = registry.create_file(
                    sha256=sha256,
                    size=size,
                    ext=ext or None,
                    source_path=fpath,
                )

                result = cascade.classify(
                    file_id=file_id,
                    output_root=output_root,
                    config=config,
                )

                elapsed_ms = int((time.perf_counter() - t0) * 1000)

                proposed_path = ""
                if result.proposed_node_id:
                    node = registry.get_taxonomy_node(result.proposed_node_id)
                    proposed_path = node["rel_path"] if node else ""

                row = {
                    "filename": fname,
                    "ext": ext,
                    "size_bytes": size,
                    "tier": result.tier,
                    "confidence": f"{result.confidence:.4f}",
                    "proposed_path": proposed_path,
                    "planned_op": result.planned_op,
                    "reasoning": result.reasoning,
                    "is_dupe": "yes" if result.dupe_of_file_id else "no",
                    "dupe_kind": result.dupe_kind or "",
                    "elapsed_ms": elapsed_ms,
                }
                writer.writerow(row)
                csvfile.flush()

                tier_key = "dupe" if result.dupe_of_file_id else str(result.tier)
                counts[tier_key] = counts.get(tier_key, 0) + 1

                bar = "#" * int(20 * i / total)
                print(
                    f"\r[{bar:<20}] {i}/{total}  T{result.tier}  {result.confidence:.2f}  {proposed_path[:30]:<30}",
                    end="",
                    flush=True,
                )

            except Exception as e:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                writer.writerow({
                    "filename": fname, "ext": ext, "size_bytes": size,
                    "tier": "err", "confidence": "", "proposed_path": "",
                    "planned_op": "", "reasoning": str(e),
                    "is_dupe": "no", "dupe_kind": "", "elapsed_ms": elapsed_ms,
                })

    print(f"\n\nDone. Results: {output_csv}")
    print("\nTier breakdown:")
    for k in ["dupe", "0", "1", "2", "3", "4", "5"]:
        label = "pre-hash" if k == "0" else ("dupe" if k == "dupe" else f"Tier {k}")
        print(f"  {label:12s}: {counts.get(k, 0)}")
    print(f"\nTotal API cost so far: ${registry.get_total_api_cost():.4f}")
    print("\nNext step: open the CSV, inspect tier/confidence distributions,")
    print("and set confidence_thresholds in config.json before the real run.")


def _hash_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
    except OSError:
        pass
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sortilege dev CLI")
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("dry-run", help="Classify files without moving anything")
    run_parser.add_argument("--source", required=True, help="Source folder to scan")
    run_parser.add_argument("--limit", type=int, default=None, help="Max files to process")
    run_parser.add_argument("--no-api", action="store_true", help="Skip Tiers 4/5 (API disabled)")
    run_parser.add_argument("--output", default=None, help="Output CSV path")

    args = parser.parse_args()
    if args.command == "dry-run":
        cmd_dry_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
