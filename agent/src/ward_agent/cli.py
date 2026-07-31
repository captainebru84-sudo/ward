"""Local demo driver: produce a signed Safety Envelope from the command line."""

import argparse
import json
import sys

from ward_agent.api import PolicyRefusal, build_service
from ward_agent.intent import UnsupportedIntent
from ward_agent.planner import SwapIntent


def main() -> None:
    parser = argparse.ArgumentParser(prog="ward-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    quote = sub.add_parser("quote", help="plan, policy-check, and sign a swap envelope")
    quote.add_argument("--user", required=True)
    quote.add_argument("--token-in", required=True, dest="token_in")
    quote.add_argument("--token-out", required=True, dest="token_out")
    quote.add_argument("--amount", required=True, type=int, help="raw units of token-in")
    quote.add_argument("--slippage-bps", type=int, default=None)

    nl = sub.add_parser("intent", help="natural language -> parsed, policy-checked, signed envelope")
    nl.add_argument("--user", required=True)
    nl.add_argument("text")

    sub.add_parser("signer", help="print the wardSigner address")
    sub.add_parser("serve", help="run the HTTP API")

    args = parser.parse_args()
    service = build_service()

    if args.command == "signer":
        print(json.dumps({"address": service.signer.address, "ephemeral": service.signer.ephemeral}))
        return

    if args.command == "serve":
        import uvicorn

        from ward_agent.api import create_app

        uvicorn.run(create_app(service), host="0.0.0.0", port=8080)
        return

    if args.command == "intent":
        if service.intent_parser is None:
            print(json.dumps({"error": "intent layer not configured"}))
            sys.exit(1)
        try:
            swap, _draft = service.intent_parser.parse(args.user, args.text)
        except UnsupportedIntent as e:
            print(json.dumps({"unsupported": str(e)}, indent=2))
            sys.exit(1)
        try:
            result = service.handle_swap(swap)
            result["parsedIntent"] = swap.model_dump()
            print(json.dumps(result, indent=2))
        except PolicyRefusal as e:
            print(
                json.dumps(
                    {"refused": True, "violations": e.violations, "parsedIntent": swap.model_dump()},
                    indent=2,
                )
            )
            sys.exit(1)
        return

    intent = SwapIntent(
        user=args.user,
        token_in=args.token_in,
        token_out=args.token_out,
        amount_in=args.amount,
        max_slippage_bps=args.slippage_bps,
    )
    try:
        print(json.dumps(service.handle_swap(intent), indent=2))
    except PolicyRefusal as e:
        print(json.dumps({"refused": True, "violations": e.violations}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
