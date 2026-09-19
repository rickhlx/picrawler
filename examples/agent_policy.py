"""Which tool calls a voice-driven agent may make on its own.

Anyone in the room can talk to the robot, so nothing here asks a human: a call
is allowed or denied on the spot. The agent also runs as an unprivileged user,
so this is the second fence, not the only one.
"""
import os
import re
import shlex

# Built-in tools that only read, or only talk to the web
READ_ONLY = {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "Skill", "TodoWrite",
             "ToolSearch"}  # loads deferred (MCP) tool definitions
# Built-in tools that write files: only inside the workspace
WRITERS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# Shell syntax that runs something the allowlist can't see, or writes a file
_FORBIDDEN = re.compile(r"`|\$\(|<\(|>\(|[<>]|(?<![&|])&(?![&])|\n")
# Command separators: every segment must start with an allowed command
_SEPARATORS = re.compile(r"\|\||&&|[|;]")


def bash_verdict(command, allowed):
    """(ok, reason) for running ``command`` when only the ``allowed`` command
    names may start a pipeline segment."""
    if _FORBIDDEN.search(command):
        return False, "no redirects, substitutions, background jobs or multi-line commands"
    for segment in _SEPARATORS.split(command):
        try:
            words = shlex.split(segment)
        except ValueError as e:
            return False, f"can't parse the command: {e}"
        if not words:
            return False, "empty command"
        name = words[0]
        if "=" in name or "/" in name:
            return False, f"{name!r}: call allowed commands by bare name, without env assignments"
        if name not in allowed:
            return False, f"{name!r} is not an allowed command (allowed: {', '.join(sorted(allowed))})"
    return True, ""


def _writable(path, root):
    """Inside the workspace, and not the files that configure the agent itself
    (project settings can define command hooks; .mcp.json starts servers)."""
    root = os.path.realpath(root)
    path = os.path.realpath(os.path.join(root, path))
    if os.path.commonpath([path, root]) != root:
        return False
    rel = os.path.relpath(path, root).split(os.sep)
    return ".claude" not in rel and rel[0] != ".mcp.json"


def verdict(tool, args, *, workspace, commands, robot_tools=(), mcp_servers=()):
    """(ok, reason) for one tool call.

    robot_tools: full names of the in-process robot tools (always allowed).
    mcp_servers: names of external MCP servers whose tools are all allowed;
    adding a server to the config is the decision to trust it.
    """
    if tool in robot_tools or tool in READ_ONLY:
        return True, ""
    if tool.startswith("mcp__") and tool.split("__")[1] in mcp_servers:
        return True, ""
    if tool == "Bash":
        return bash_verdict(args.get("command", ""), commands)
    if tool in WRITERS:
        path = args.get("file_path") or args.get("notebook_path") or ""
        if path and _writable(path, workspace):
            return True, ""
        return False, f"can only write inside {workspace}, and not its .claude/ or .mcp.json"
    return False, f"{tool} is not available here"
