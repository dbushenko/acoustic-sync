"""Run with python -m acoustic_sync.web."""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Acoustic Sync local web companion")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-dir", type=str)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        import uvicorn
        from pathlib import Path
        from . import create_app
        app = create_app(Path(args.state_dir) if args.state_dir else None)
    except ImportError as exc:
        parser.exit(2, f"Web dependencies missing: install acoustic-sync[web]. ({exc})\n")
    uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
