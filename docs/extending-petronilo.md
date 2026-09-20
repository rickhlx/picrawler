# Teaching Petronilo new tricks

Four ways to give him something new, from cheapest to most involved. The first
two need no restart; the rest do.

| You want him to | Add | Restart? |
|-----------------|-----|----------|
| Follow a procedure you wrote down | A skill | No |
| Reach another service | An MCP server | No |
| Run a command | An entry in `AGENT_COMMANDS` | Yes |
| Do something with his body or senses | An action or a robot tool | Yes |

Skills and MCP servers are read when a conversation starts. Anything in Python
needs `make deploy`.

## A skill

A skill is a folder with a `SKILL.md` — instructions he reads when the task
matches. Good for procedures: how the family likes the shopping list written,
what to check before saying the weather is bad, how to phrase a reminder.

```bash
scp -r mi-skill picrawler:/tmp/
ssh picrawler "sudo mv /tmp/mi-skill /home/petronilo/.claude/skills/ && \
               sudo chown -R petronilo: /home/petronilo/.claude/skills/mi-skill"
```

He can read a skill's files but only runs allowlisted commands, so **skills
that are instructions work and skills that ship scripts do not**. Write the
skill to use the tools he already has.

## An MCP server

Add it to `examples/petronilo_mcp.json` on the Pi, in Claude Code's format:

```json
{
  "mcpServers": {
    "casa": {
      "command": "/usr/local/bin/home-assistant-mcp",
      "args": ["--config", "/etc/casa.toml"],
      "env": {"TOKEN": "..."}
    }
  }
}
```

```bash
ssh picrawler "chmod 600 ~/picrawler/examples/petronilo_mcp.json"
```

The file holds tokens, so it is `600` and git-ignored. Servers start as the
`petronilo` user, and **every tool of a configured server is allowed** — the
policy trusts what you put in this file, so put in things you would let a
stranger in your living room use. Install the runtime first: the Pi has no
`node`/`npx` and no `uv`/`uvx`.

## A command

```python
AGENT_COMMANDS = ["date", "cal", "uptime", "free", "df", "jq", "gh"]
```

Install the tool, log it in as the agent user, add the name, deploy:

```bash
ssh picrawler "sudo apt install gh && sudo -u petronilo -H gh auth login"
```

**Never allowlist a command that can run other commands** — `sh`, `bash`,
`python3`, `npx`, `xargs`, `env`, `sudo`, `find` (it has `-exec`) — **or one
that reads arbitrary files** — `cat`, `grep`, `less`. The policy only checks
the first word of each pipeline segment, so either kind hands over everything
behind it. `curl` is out too: `WebFetch` covers fetching, and `curl` can write
files with `-o` or send them with `-d @file`.

For commands that are useful but have a few dangerous corners, block the
corners instead of the command: `DENIED_SUBCOMMANDS` and `DENIED_FLAGS` in
`agent_policy.py` are how `gh` and `jq` are allowed at all.

Run the policy tests after touching any of this:

```bash
python3 -m unittest tests.test_agent_policy
```

## An action (his body)

Actions are named moves the agent picks with the `move` tool. Adding one:

1. Write the move. A trick goes in `picrawler/tricks.py` and gets registered in
   `TRICKS`; anything else is a method on `Picrawler` or an existing
   `MoveList` entry. See [Writing moves](writing-moves.md).
2. Add it to `ACTION_MAP` in `examples/voice_active_crawler.py`:

```python
"turn 180": ("turn_angle", {"degrees": 180, "side": "left", "speed": 70}),
```

   The first element is a `Picrawler` method, or `"self:<method>"` for one on
   the assistant. The `move` tool's enum is built from `ACTION_MAP`, so the
   agent can use it immediately.

3. Add Spanish names to `ACTION_ALIASES` — both accented and unaccented, since
   what comes back from transcription is unpredictable.
4. If it drives every servo at once, add it to `HEAVY_TRICKS`/`HEAVY_ACTIONS`
   so it is refused on a low battery *before* he promises to do it.
5. Tell him about it in `AGENT_INSTRUCTIONS` (and `INSTRUCTIONS`, for the
   non-agent path) in `18_voice_active_crawler_gpt.py` — in Spanish, saying
   when to use it, not just that it exists.

## A tool (his senses)

Robot tools live in `robot_tools()` in `examples/petronilo_agent.py` and run
in the root voice service, where the hardware is. They are the right shape when
something needs more than one move, or needs to report back:

```python
@tool("where", "Look around for something and say where it is, without "
      "walking to it. Takes up to a minute.", {"object": str})
async def where(args):
    return _text(json.dumps(await asyncio.to_thread(va.locate, args["object"]),
                            ensure_ascii=False))
```

Then add it to the list `robot_tools` returns.

Three rules learned the hard way:

**Anything that moves the body goes through the action thread.** Use
`va.run_on_action_thread(...)` — `seek` and `locate` route themselves — or the
idle fidgets will drive the servos while your tool is walking.

**Loops belong in a tool, not in a skill.** A skill cannot turn four times and
look four times: `max_actions` caps the agent at one `move` per reply. That cap
is why "where is the dog" is a tool and not a page of instructions.

**Announce before you move.** A tool that moves should call
`va._announce_first()` first, which waits for the sentence he just said to
finish playing. Without it the body starts turning while "déjame echar un ojo"
is still being synthesized, and the narration lands after the movement.

Return JSON for anything with structure — he phrases it himself, in character —
and name the keys so a model can read them without a schema (`distance_cm`, not
`d`).

## Changing who he is

Personality lives in [`examples/petronilo/SOUL.md`](../examples/petronilo/SOUL.md):
identity, voice, albures, limits, what he knows about his own body. Edit and
restart.

Keep the split honest. `SOUL.md` is character; `AGENT_INSTRUCTIONS` is
operation — which tools exist and when to reach for them. When a change is
"he should be funnier about X" it belongs in the soul. When it is "he should
call `where` instead of `find` when nobody asked him to walk", it belongs in
the instructions.

## Spending and limits

```python
AGENT_BUDGET_USD = 0.50        # one conversation
AGENT_DAILY_BUDGET_USD = 5.00  # a day, then BUDGET_PHRASE
```

Anyone in the room can talk to him, which is why both caps stay on. `make
status` shows the day's spend. A new tool that calls a paid API spends from the
same budget — worth remembering before you wire in something that runs on a
schedule.
