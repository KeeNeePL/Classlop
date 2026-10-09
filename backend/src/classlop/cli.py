import argparse
import logging


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="classlop")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("web", help="serve the API and the dashboard on :8000")
    commands.add_parser("migrate", help="apply every area's migrations")
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
