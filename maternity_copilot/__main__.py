import argparse
import json

from .core import OPTIONS, evaluate, load_model, retrieve, train
from .server import make_server


def main():
    parser = argparse.ArgumentParser(description="Synthetic educational resource matcher, not medical advice.")
    parser.add_argument("--model", default="models/tfidf.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("train")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--split", choices=["development", "held_out"], default="held_out")
    evaluation.add_argument("--k", type=int, choices=range(1, 7), default=3)
    matching = commands.add_parser("match")
    for key, values in OPTIONS.items():
        matching.add_argument("--" + key, choices=values, required=True)
    serving = commands.add_parser("serve")
    serving.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        if args.command == "train":
            model = train(args.model)
            print(json.dumps({"model": args.model, "documents": len(model["vectors"]),
                              "terms": len(model["idf"]), "catalog_sha256": model["catalog_sha256"]}, indent=2))
            return
        model = load_model(args.model)
        if args.command == "evaluate":
            print(json.dumps(evaluate(model, args.split, args.k), indent=2))
        elif args.command == "match":
            print(json.dumps(retrieve(model, {key: getattr(args, key) for key in OPTIONS}), indent=2))
        else:
            with make_server(model, args.port) as server:
                print(f"Educational prototype: http://127.0.0.1:{server.server_port}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
