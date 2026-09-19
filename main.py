"""CLI uses the exact same Service, Provider, Retriever and global job lock as the UI."""

import argparse
import json
import time
import uuid

from src.config import CACHE_DIR, DATA_DIR, USER_DATA_DIR, LearningOptions
from src.runtime import create_runtime


def main() -> int:
    parser = argparse.ArgumentParser(description="Study-with-AI local search and Codex generation")
    parser.add_argument("--subject", help="category/subject")
    parser.add_argument("--question")
    parser.add_argument("--search-only", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    runtime = create_runtime(str(DATA_DIR), str(USER_DATA_DIR), str(CACHE_DIR))
    try:
        if args.diagnose:
            print(json.dumps(runtime.provider.diagnostics(), ensure_ascii=False, indent=2))
            return 0
        if not args.subject or not args.question:
            print(json.dumps(runtime.retriever.discover_subjects(), ensure_ascii=False))
            return 0
        if args.search_only:
            print(json.dumps(runtime.retriever.search(args.subject, args.question), ensure_ascii=False, indent=2))
            return 0
        request = runtime.service.prepare(
            "answer", args.subject, uuid.uuid4().hex, {"question": args.question}, LearningOptions()
        )
        job_id = runtime.jobs.submit(
            request.kind,
            request.scope,
            request.to_dict(),
            request.request_id,
            lambda cancel: runtime.service.execute(request, cancel),
        )
        try:
            while True:
                job = runtime.jobs.get(job_id)
                if job and job["state"] not in ("queued", "running"):
                    if job["state"] == "succeeded":
                        print(job["result"]["markdown"])
                        return 0
                    print(job["error_message"])
                    return 1
                time.sleep(0.1)
        except KeyboardInterrupt:
            runtime.jobs.cancel(job_id)
            return 130
    finally:
        runtime.jobs.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
