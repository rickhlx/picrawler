"""Which tool calls a voice-driven agent may make on its own.

Anyone in the room can talk to the robot, so nothing here asks a human: a call
is allowed or denied on the spot. The agent also runs as an unprivileged user,
so this is the second fence, not the only one.

Threat model for Bash: the allowlist only checks the first word of each
pipeline segment, so a command that can itself run other commands, read
arbitrary files, or write files outside the workspace defeats it. That's why
`sh`, `python3`, `xargs`, `env` and `sudo` (run other commands) and `cat` and
`grep` (read arbitrary files) must never be added to an allowlist passed in
here. For commands that are useful but have a few dangerous flags or
subcommands (`curl`, `jq`, `gh`), DENIED_FLAGS and DENIED_SUBCOMMANDS below
block those specifically instead of blocking the whole command. None of this
is a sandbox: it's pattern matching over argv, so it only has to hold up
against a Bash tool call, not a determined shell.
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

# Shell syntax that runs something the allowlist can't see, writes a file, or
# expands a variable (the process environment has ANTHROPIC_API_KEY in it,
# and there's no legitimate need for a shell variable in any allowed command)
_FORBIDDEN = re.compile(r"`|\$|<\(|>\(|[<>]|(?<![&|])&(?![&])|\n")
# Command separators: every segment must start with an allowed command
_SEPARATORS = re.compile(r"\|\||&&|[|;]")

# Subcommands that let an otherwise-fine command run something else.
# gh alias set NAME '!cmd' and gh extension install run arbitrary commands;
# gh config set pager picks the program gh pipes its output through.
DENIED_SUBCOMMANDS = {
    "gh": {"alias", "extension", "extensions", "config"},
}

# Flags that turn a read-only-looking command into a file write or a read of
# an arbitrary file, keyed by command name. curl -o/-O/-T/-K can write
# ~/.claude/settings.json (hooks run commands) or the workspace .mcp.json
# (starts MCP servers); -d/-F/--data*/-T read a local file back out over the
# network; -w/--trace*/-D/-c write files too. jq -f/--rawfile/--slurpfile
# read arbitrary files as the program or as input.
DENIED_FLAGS = {
    "curl": {
        "-o", "-O", "--output", "--remote-name", "--remote-name-all",
        "-K", "--config", "-T", "--upload-file", "-F", "--form",
        "--data-binary", "-d", "--data", "--data-raw", "--data-urlencode",
        "--data-ascii", "-w", "--write-out", "--trace", "--trace-ascii",
        "--dump-header", "-D", "--cookie-jar", "-c", "--netrc-file",
    },
    "jq": {"-f", "--from-file", "--rawfile", "--slurpfile", "--args", "--jsonargs"},
}


def _denied_flag(name, words):
    """Reason this segment isn't allowed for one of DENIED_FLAGS's commands,
    or None. Generic across commands so a maintainer can allowlist curl or jq
    without reopening the file-write/file-read holes their flags offer.

    A flag matches if a word equals it, or (long form) starts with it
    followed by ``=``, or (single-letter short form) its letter appears in a
    single-dash cluster, e.g. ``-ofile``, ``-d@x`` or ``-sSo``.
    """
    denied = DENIED_FLAGS.get(name)
    if not denied:
        return None
    letters = {f[1] for f in denied if len(f) == 2}
    for word in words[1:]:
        if word in denied:
            return word
        for flag in denied:
            if flag.startswith("--") and word.startswith(flag + "="):
                return flag
        if word.startswith("-") and not word.startswith("--"):
            hit = letters & set(word[1:].split("=")[0])
            if hit:
                return "-" + sorted(hit)[0]
    if name == "curl":
        # @file means "read this file" wherever curl accepts it, attached to
        # a flag or not, and however it's spelled (--data=@file included)
        for word in words[1:]:
            if word.startswith("@") or "=@" in word:
                return "@"
    if name == "jq":
        # jq is only ever meant to read the pipeline's stdin here: the
        # filter is the one positional argument allowed, anything after it
        # would be a file for jq to read instead
        seen_filter = False
        for word in words[1:]:
            if word.startswith("-"):
                continue
            if seen_filter:
                return word
            seen_filter = True
    return None


def bash_verdict(command, allowed):
    """(ok, reason) for running ``command`` when only the ``allowed`` command
    names may start a pipeline segment."""
    if _FORBIDDEN.search(command):
        return False, "no redirects, substitutions, variables, background jobs or multi-line commands"
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
        if name in DENIED_SUBCOMMANDS:
            sub = next((w for w in words[1:] if not w.startswith("-")), None)
            if sub in DENIED_SUBCOMMANDS[name]:
                return False, f"{name} {sub}: not allowed"
        if name == "gh" and any(w.startswith("!") for w in words[1:]):
            return False, f"{name}: ! commands not allowed"
        flag = _denied_flag(name, words)
        if flag:
            return False, f"{name} {flag}: not allowed"
    return True, ""


def _under(path, root):
    """Whether the resolved absolute path is root or inside it."""
    root = os.path.realpath(root)
    return os.path.commonpath([path, root]) == root


def _writable(path, workspace):
    """Inside the workspace, and not the files that configure the agent
    itself: project settings can define command hooks, .mcp.json starts
    servers, and a project CLAUDE.md or .claude.json is loaded automatically
    from the workspace, so a writable one is a persistence vector."""
    if not _under(path, workspace):
        return False
    rel = os.path.relpath(path, os.path.realpath(workspace)).split(os.sep)
    if ".claude" in rel:
        return False
    if rel[0] in (".mcp.json", ".claude.json"):
        return False
    if rel[0].lower() == "claude.md":
        return False
    return True


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
        return False, f"can only write inside {workspace}, and not its .claude/, .mcp.json, CLAUDE.md or .claude.json"
    return False, f"{tool} is not available here"
