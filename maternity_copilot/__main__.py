import argparse
import json
from pathlib import Path

from .core import DATA, OPTIONS, evaluate, load_model, retrieve, train, write_json
from .server import make_server
from .audit import browse, compare_reports, coverage, explain, inspect_model, sweep


def main():
    parser = argparse.ArgumentParser(description="Synthetic educational resource matcher, not medical advice.")
    parser.add_argument("--model", default="models/tfidf.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("train")
    commands.add_parser("inspect")
    commands.add_parser("coverage")
    sweeping = commands.add_parser("sweep")
    sweeping.add_argument("--k", type=int, choices=range(1, 7), default=3)
    comparing = commands.add_parser("compare")
    comparing.add_argument("--before", required=True)
    comparing.add_argument("--after", required=True)
    browsing = commands.add_parser("browse")
    for key, values in OPTIONS.items():
        browsing.add_argument("--" + key, choices=values)
    browsing.add_argument("--offset", type=int, default=0)
    browsing.add_argument("--limit", type=int, default=6)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--split", choices=["development", "held_out"], default="held_out")
    evaluation.add_argument("--k", type=int, choices=range(1, 7), default=3)
    evaluation.add_argument("--output", help="Atomically save a reproducible JSON report.")
    for command in ("match", "explain"):
        matching = commands.add_parser(command)
        for key, values in OPTIONS.items():
            matching.add_argument("--" + key, choices=values, required=True)
    serving = commands.add_parser("serve")
    serving.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "serve" and not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535; use 0 to choose an available port.")
    try:
        if args.command == "coverage":
            print(json.dumps(coverage(), indent=2))
            return
        if args.command == "compare":
            print(json.dumps(compare_reports(args.before, args.after), indent=2))
            return
        if args.command == "inspect":
            print(json.dumps(inspect_model(args.model), indent=2))
            return
        if args.command == "browse":
            filters = {key: getattr(args, key) for key in OPTIONS if getattr(args, key) is not None}
            print(json.dumps(browse(filters, args.offset, args.limit), indent=2))
            return
        if args.command == "train":
            model = train(args.model)
            print(json.dumps({"model": args.model, "documents": len(model["vectors"]),
                              "terms": len(model["idf"]), "catalog_sha256": model["catalog_sha256"]}, indent=2))
            return
        model = load_model(args.model)
        if args.command == "evaluate":
            report = evaluate(model, args.split, args.k)
            if args.output:
                target = Path(args.output).resolve()
                if target == Path(args.model).resolve() or target.is_relative_to(DATA.resolve()):
                    raise ValueError("Report output must not replace the model or packaged data.")
                write_json(target, report)
            print(json.dumps(report, indent=2))
        elif args.command == "sweep":
            print(json.dumps(sweep(model, args.k), indent=2))
        elif args.command == "match":
            print(json.dumps(retrieve(model, {key: getattr(args, key) for key in OPTIONS}), indent=2))
        elif args.command == "explain":
            print(json.dumps(explain(model, {key: getattr(args, key) for key in OPTIONS}), indent=2))
        else:
            try:
                server = make_server(model, args.port)
            except OSError:
                parser.exit(2, f"Error: Could not start the educational dashboard on port {args.port}. Choose another --port or use --port 0 for an available port.\n")
            with server:
                print(f"Educational prototype: http://127.0.0.1:{server.server_port}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
