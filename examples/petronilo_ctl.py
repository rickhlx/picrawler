#!/usr/bin/env python3
"""CLI client for control.py: talk to a running Petronilo without the wake
word (say something, ask him something, stop him, schedule a reminder).

Examples:
    petronilo_ctl.py say "ya llegue"
    petronilo_ctl.py ask "que hora es" --quiet
    petronilo_ctl.py stop
    petronilo_ctl.py remind +20m "saca la carne del congelador"
    petronilo_ctl.py remind 08:00 "buenos dias" --repeat daily
    petronilo_ctl.py jobs
    petronilo_ctl.py cancel 3
    petronilo_ctl.py status

Runs on the Pi as whoever can reach /run/petronilo.sock (root, since the
socket is chmod 0o600 and owned by the voice service).
"""
import argparse
import re
import sys
from datetime import datetime, timedelta

from control import DEFAULT_SOCKET, request

_RELATIVE_RE = re.compile(r"^\+(\d+)([mhd])$")
_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_when(when, now=None):
    """Turn WHEN into an ISO-8601 string. Accepts ISO-8601 already, HH:MM
    (today, or tomorrow if that time already passed), or +Nm/+Nh/+Nd relative
    to now. Raises ValueError if none of those parse."""
    now = now or datetime.now()

    m = _RELATIVE_RE.match(when)
    if m:
        amount, unit = int(m.group(1)), m.group(2)
        delta = {
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }[unit]
        return (now + delta).isoformat()

    m = _HHMM_RE.match(when)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"bad time: {when!r}")
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.isoformat()

    try:
        datetime.fromisoformat(when)
    except ValueError:
        raise ValueError(f"can't parse WHEN: {when!r} (use ISO-8601, HH:MM, or +20m/+2h/+1d)")
    return when


def build_parser():
    parser = argparse.ArgumentParser(description="Talk to a running Petronilo without the wake word.")
    parser.add_argument("--socket", default=DEFAULT_SOCKET, help="control socket path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_say = sub.add_parser("say", help="say something out loud right now")
    p_say.add_argument("text")

    p_ask = sub.add_parser("ask", help="ask him something; runs one autonomous agent turn")
    p_ask.add_argument("text")
    p_ask.add_argument("--quiet", action="store_true", help="answer in text only, not aloud")

    sub.add_parser("stop", help="cut whatever he is saying or doing")

    p_remind = sub.add_parser("remind", help="schedule a reminder")
    p_remind.add_argument("when", help="ISO-8601, HH:MM, or +20m/+2h/+1d")
    p_remind.add_argument("text")
    p_remind.add_argument("--kind", choices=["say", "ask"], default="say",
                           help="say it, or run an agent turn with it (default: say)")
    p_remind.add_argument("--repeat", choices=["daily", "weekly"], default=None)

    sub.add_parser("jobs", help="list scheduled jobs")

    p_cancel = sub.add_parser("cancel", help="cancel a scheduled job")
    p_cancel.add_argument("id")

    sub.add_parser("status", help="battery, idle state, spend today, scheduled jobs")

    return parser


def dispatch(args):
    if args.command == "say":
        return request("say", args.socket, text=args.text)
    if args.command == "ask":
        return request("ask", args.socket, text=args.text, speak=not args.quiet)
    if args.command == "stop":
        return request("stop", args.socket)
    if args.command == "remind":
        when = parse_when(args.when)
        return request("remind", args.socket, when=when, text=args.text,
                        kind=args.kind, repeat=args.repeat)
    if args.command == "jobs":
        return request("jobs", args.socket)
    if args.command == "cancel":
        return request("cancel", args.socket, id=args.id)
    if args.command == "status":
        return request("status", args.socket)
    raise ValueError(f"unknown command {args.command!r}")


def print_result(command, result):
    if command == "jobs":
        if not result:
            print("(no scheduled jobs)")
        for line in result:
            print(line)
    elif command == "status":
        for key, value in result.items():
            print(f"{key}: {value}")
    else:
        print(result)


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        reply = dispatch(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"error: {e} (is petronilo.service running? needs sudo)", file=sys.stderr)
        return 1

    if not reply.get("ok"):
        print(f"error: {reply.get('error', 'unknown error')}", file=sys.stderr)
        return 1

    print_result(args.command, reply.get("result"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
