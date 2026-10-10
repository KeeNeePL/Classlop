import argparse
import logging


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="classlop")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("web", help="serve the API and the dashboard on :8000")
    commands.add_parser("migrate", help="apply every area's migrations")
    commands.add_parser("rebuild-index", help="rebuild the items search index from Postgres")
    commands.add_parser("worker", help="run background jobs from the queue")
    commands.add_parser("scheduler", help="dev only: fire due schedules onto the queue")
    commands.add_parser("ping", help="run a shared.ping job through the queue and the worker")
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
    elif args.command == "worker":
        import asyncio

        from classlop.shared.worker import run

        asyncio.run(run())
    elif args.command == "scheduler":
        import asyncio

        from classlop.shared.schedule import run_scheduler

        asyncio.run(run_scheduler())
    elif args.command == "ping":
        import asyncio

        from classlop.shared.jobs import ping

        raise SystemExit(0 if asyncio.run(ping()) else 1)
