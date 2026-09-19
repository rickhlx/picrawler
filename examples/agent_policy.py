"""Which tool calls a voice-driven agent may make on its own.

Anyone in the room can talk to the robot, so nothing here asks a human: a call
is allowed or denied on the spot. The agent also runs as an unprivileged user,
so this is the second fence, not the only one.
"""
import os
import re
import shlex

# Built-in tools that touch no local files
HARMLESS = {"WebSearch", "WebFetch", "Skill", "TodoWrite",
            "ToolSearch"}  # loads deferred (MCP) tool definitions
# Built-in tools that read files: only inside the read roots
READERS = {"Read", "Glob", "Grep"}
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


def _under(path, root):
    """Whether the resolved absolute path is root or inside it."""
    root = os.path.realpath(root)
    return os.path.commonpath([path, root]) == root


def _writable(path, workspace):
    """Inside the workspace, and not the files that configure the agent itself
    (project settings can define command hooks; .mcp.json starts servers)."""
    if not _under(path, workspace):
        return False
    rel = os.path.relpath(path, os.path.realpath(workspace)).split(os.sep)
    return ".claude" not in rel and rel[0] != ".mcp.json"


def verdict(tool, args, *, workspace, commands, robot_tools=(), mcp_servers=(), read_roots=()):
    """(ok, reason) for one tool call.

    read_roots: directories besides the workspace that file tools may read
    (the skills directory). The unprivileged user can read more than that,
    world-readable files included; this keeps the agent's own tools out.

    robot_tools: full names of the in-process robot tools (always allowed).
    mcp_servers: names of external MCP servers whose tools are all allowed;
    adding a server to the config is the decision to trust it.
    """
    if tool in robot_tools or tool in HARMLESS:
        return True, ""
    # relative paths are relative to the agent's cwd, the workspace
    path = args.get("file_path") or args.get("notebook_path") or args.get("path") or ""
    path = os.path.realpath(os.path.join(workspace, path))
    if tool in READERS:
        roots = (workspace, *read_roots)
        if any(_under(path, r) for r in roots):
            return True, ""
        return False, "can only read " + ", ".join(roots)
    if tool.startswith("mcp__") and tool.split("__")[1] in mcp_servers:
        return True, ""
    if tool == "Bash":
        return bash_verdict(args.get("command", ""), commands)
    if tool in WRITERS:
        if _writable(path, workspace) and path != os.path.realpath(workspace):
            return True, ""
        return False, f"can only write inside {workspace}, and not its .claude/ or .mcp.json"
    return False, f"{tool} is not available here"
