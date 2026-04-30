from __future__ import annotations

import argparse
import json
import sys
import traceback

from launcher_core_parts.runtime import updater_log
from launcher_core_parts.update_manager import apply_update_job


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="Updater", description="GenericAgent Launcher external updater")
    parser.add_argument("--job", required=True, help="Path to update job json")
    return parser.parse_args(argv)


def run(argv=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    job_path = str(args.job or "").strip()
    if not job_path:
        sys.stderr.write("missing --job\n")
        return 2
    try:
        result = apply_update_job(job_path)
    except Exception as e:
        updater_log(f"[fatal] updater failed: {e}")
        updater_log(traceback.format_exc())
        sys.stderr.write(str(e) + "\n")
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0 if bool(result.get("ok", False)) else 3


if __name__ == "__main__":
    raise SystemExit(run())
