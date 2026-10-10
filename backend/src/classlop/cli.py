import argparse
import logging


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="classlop")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("web", help="serve the API and the dashboard on :8000")
    commands.add_parser("migrate", help="apply every area's migrations")
    commands.add_parser("rebuild-index", help="rebuild the items search index from Postgres")
    load = commands.add_parser(
        "load-knowledge-base", help="upload an Exemplar bundle to S3 and queue its load"
    )
    load.add_argument("bundle", help="a JSONL bundle file")
    commands.add_parser("worker", help="run background jobs from the queue")
    commands.add_parser("scheduler", help="dev only: fire due schedules onto the queue")
    commands.add_parser("ping", help="run a shared.ping job through the queue and the worker")
    commands.add_parser("whoami", help="read the Teacher's name from Graph in a worker job")
    commands.add_parser("openapi", help="print the API's OpenAPI schema")
    evaluation = commands.add_parser(
        "eval-grading", help="grade an evaluation set with the real models and report"
    )
    evaluation.add_argument("set", nargs="?", default="set-01")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    from classlop.shared.llm import configure_tracing

    configure_tracing()

    if args.command == "web":
        import uvicorn

        uvicorn.run("classlop.dashboard.app:create_app", factory=True, host="0.0.0.0", port=8000)
    elif args.command == "migrate":
        from classlop.shared.migrate import migrate

        migrate()
    elif args.command == "rebuild-index":
        import asyncio

        from classlop.items.index import rebuild

        print(f"indexed {asyncio.run(rebuild())} items")
    elif args.command == "load-knowledge-base":
        import asyncio
        from pathlib import Path

        from classlop.items.exemplars import upload

        print(f"queued the load of {asyncio.run(upload(Path(args.bundle)))}")
    elif args.command == "worker":
        import asyncio

        from classlop.shared.worker import run

        asyncio.run(run())
    elif args.command == "scheduler":
        import asyncio

        from classlop.shared.schedule import run_scheduler

        asyncio.run(run_scheduler())
    elif args.command in ("ping", "whoami"):
        import asyncio

        from classlop.shared.jobs import ping

        kind = "shared.ping" if args.command == "ping" else "teams.whoami"
        raise SystemExit(0 if asyncio.run(ping(kind)) else 1)
    elif args.command == "openapi":
        import json

        from classlop.dashboard.app import create_app

        print(json.dumps(create_app().openapi(), indent=2))
    elif args.command == "eval-grading":
        import asyncio

        from classlop.grading.evaluation import evaluate, print_report

        # psycopg's async mode needs the selector loop, which Windows does not default to.
        report = asyncio.run(evaluate(args.set), loop_factory=asyncio.SelectorEventLoop)
        print_report(args.set, report)
