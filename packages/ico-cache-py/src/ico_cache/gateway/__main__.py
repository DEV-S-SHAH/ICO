"""CLI entry point for the ICO-Cache OpenAI gateway."""

import argparse
import sys

import uvicorn

from .app import create_app
from .config import GatewayConfig


def main():
    """Run the ICO-Cache OpenAI gateway."""
    parser = argparse.ArgumentParser(
        description="ICO-Cache OpenAI-compatible gateway",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host to bind to (default: from config or 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (default: from config or 8080)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (default: 1)",
    )

    args = parser.parse_args()

    # Load configuration from environment
    config = GatewayConfig.from_env()

    # Override with CLI arguments
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port

    # Create app
    app = create_app(config)

    print(f"Starting ICO-Cache OpenAI Gateway on {config.host}:{config.port}")
    print(f"Configured providers: {list(config.providers.keys())}")

    # Run with uvicorn
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        reload=args.reload,
        workers=args.workers if not args.reload else 1,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    sys.exit(main())
