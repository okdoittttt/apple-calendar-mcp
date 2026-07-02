# apple-calendar MCP Server

A personal MCP server for macOS Calendar and Reminders, built on
[EventKit](https://developer.apple.com/documentation/eventkit) via PyObjC.
Runs locally over stdio - no network calls, no cloud service. Built to be
used with Claude Desktop (connector name: `apple-calendar`), but works with
any MCP stdio client.

Tools cover the full Calendar/Reminders CRUD surface, a hashtag-based tag
system (`tags_*`), scheduling convenience tools (`agenda_*`, `quick_event`,
`reschedule_event`, `find_free_slots`), and hot-restart admin tools
(`server_status`, `server_restart`).

## Requirements

- macOS 14+ (uses the modern `requestFullAccessTo...` permission APIs, with
  a fallback to the legacy API on older macOS)
- Python 3.10+, managed via [uv](https://docs.astral.sh/uv/)

## Install

```bash
cd apple-calendar-mcp
uv sync
```

## Grant permissions

EventKit ties Calendar/Reminders authorization to whichever process first
requests it (the "responsible process"). Two ways to grant access:

**Option A - recommended, run once from Terminal:**

```bash
uv run python scripts/setup_permissions.py
```

This should trigger the system permission dialogs for Calendar and
Reminders under Terminal's identity. Click "Allow" on both.

**Option B - manual:**

Open **System Settings > Privacy & Security > Calendar** (and **Reminders**)
and enable access for Terminal, your Python interpreter, or Claude Desktop -
whichever ends up listed there after the server has run at least once.

If a tool call returns `"error": "permission_denied"`, check
`eventkit_check_permissions` for the current status and instructions, or
re-run the setup script.

> Note: when this server runs as a subprocess of Claude Desktop, macOS may
> attribute the permission prompt to Claude Desktop instead of showing it at
> all (background subprocesses often can't present UI). If no dialog
> appears after adding the server to Claude Desktop, run the setup script
> from Terminal first, then restart Claude Desktop.

## Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`
(this repo's setup already did this on this machine - see below). The
`mcpServers` key becomes the connector name shown in Claude Desktop:

```json
{
  "mcpServers": {
    "apple-calendar": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/apple-calendar-mcp",
        "run", "python", "-m", "apple_calendar_mcp.server"
      ]
    }
  }
}
```

Restart Claude Desktop (or use `server_restart`, see below) after editing.

## Tools

### Permissions

| Tool | Description |
|---|---|
| `eventkit_check_permissions` | Calendar/Reminders authorization status + instructions |

### Calendar

| Tool | Description |
|---|---|
| `calendar_list_calendars` | List all calendars |
| `calendar_list_events` | List events in a date range |
| `calendar_get_event` | Get one event by id |
| `calendar_search_events` | Text search over title/location/notes, optional tag filter |
| `calendar_create_event` | Create an event (location, notes, url, tags) |
| `calendar_edit_event` | Edit an event; `span` required for recurring events |
| `calendar_delete_event` | Delete an event; `span` required for recurring events |

### Reminders

| Tool | Description |
|---|---|
| `reminders_list_lists` | List all reminder lists |
| `reminders_list` | List reminders, filter by list/completed/due date |
| `reminders_get` | Get one reminder by id |
| `reminders_search` | Text search over title/notes, optional tag filter |
| `reminders_create` | Create a reminder (due date, priority, tags) |
| `reminders_edit` | Edit a reminder |
| `reminders_complete` | Mark a reminder completed |
| `reminders_delete` | Delete a reminder |

### Tags

Tags are stored as `#hashtag`s appended to the notes field (EventKit has no
native tag concept). Normalization: lowercase, spaces/hyphens -> underscore,
non-alphanumeric stripped. Because they live in `notes`, tags sync via
iCloud and are visible/searchable in the stock Calendar/Reminders apps.

| Tool | Description |
|---|---|
| `tags_list` | All tags in use, with item counts |
| `tags_rename(old_tag, new_tag, scope)` | Rename a tag; `scope`: `events`\|`reminders`\|`all` |
| `tags_merge(from_tag, into_tag, scope)` | Merge one tag into another |
| `tags_delete(tag, scope)` | Remove a tag everywhere it appears |

All three take **exact** tag names (no fuzzy/partial matching) since these
are bulk, irreversible edits. They only ever rewrite the hashtag line in
`notes` - the rest of the notes body is preserved exactly.

**Scan window caveat:** `tags_list`/`tags_rename`/`tags_merge`/`tags_delete`
need to see "all" events, but EventKit's date-range predicate has a
practical ~4-year limit per call. These tools chunk the scan into 3-year
windows covering 6 years back to 6 years forward (12 years total, capped at
5000 events) - events further out won't be seen. Reminders have no such
limit and are fetched in one call (capped at 20000). If a scan hits its
cap, the response includes a `"warning"` field.

**Recurring events caveat:** bulk tag edits reuse the same
`calendarItemWithIdentifier_` + `EKSpanThisEvent` machinery as
`calendar_edit_event`. For a recurring series, that resolves to one
representative occurrence, not every visible occurrence - the same
limitation the base edit tool has.

### Custom scheduling tools

| Tool | Description |
|---|---|
| `agenda_today` | Human-readable agenda for today (events + reminders due) |
| `agenda_range(start_date, end_date)` | Same, over a date range |
| `quick_event(text)` | Create an event from a short natural-language line |
| `reschedule_event(event_id, new_start)` | Move an event, keeping its duration |
| `find_free_slots(date, working_hours, min_duration_minutes)` | Free gaps within working hours (all-day events ignored) |

`quick_event` uses a small heuristic parser (no external NLP dependency, by
design - this project only depends on `mcp[cli]` and pyobjc). It recognizes:

- Relative days: `today`, `tomorrow`, `mon`..`sun` / full weekday names
- Explicit dates: `YYYY-MM-DD`
- Times: `3pm`, `3:30pm`, `15:00` (optionally preceded by `at`)
- Duration: `for 30 minutes`, `for 2 hours`
- Trailing `#hashtags` -> tags

Defaults: 1 hour duration; if no time is found, 09:00 (or 08:00/12:00/19:00
if the leftover title mentions breakfast/lunch/dinner). Anything not
matched by these patterns stays in the title. It's best-effort - review the
returned `event` before relying on it for anything time-sensitive.

### Server admin

| Tool | Description |
|---|---|
| `server_status` | pid, version, uptime, tool count |
| `server_restart` | Hot-restart the process without quitting Claude Desktop |
| `server_stop` | Stop the process (no relaunch) - use to pause Calendar/Reminders access |

#### How `server_restart` works, and what we verified

`server_restart` spawns a background thread that sleeps briefly (default
0.75s, configurable via `delay_seconds`), flushes stdout/stderr, then calls
`os.execv` to replace the current process image with a fresh
`python -m apple_calendar_mcp.server` - picking up any code changes on disk.

We tested this directly against the raw MCP Python client (not through
Claude Desktop's UI, which we can't drive from this environment) and
observed:

- The stdio pipe's file descriptors **survive** `execv`- bytes keep
  flowing between the client and the new process.
- The new process's pid is different and `uptime_seconds` resets to ~0,
  confirming the restart happened (this is the mechanism `server_status` is
  for).
- The **MCP/JSON-RPC session does not survive** - it's in-memory state that
  resets when the process image is replaced. A tool call sent on the old
  session immediately after restart gets rejected
  (`Invalid request parameters` / "request before initialization was
  complete").
- Re-sending the MCP `initialize` handshake **on the same stdio pipe**
  after the restart fully recovers the session - new pid, reset uptime,
  every tool callable again. No new subprocess, no Claude Desktop restart.

What we could **not** verify directly: whether Claude Desktop's own client
automatically re-sends `initialize` after getting a request-rejected error
from a tool it just called (i.e., does it self-heal, or does the connector
appear "stuck" until you interact with it again). If tools stop responding
right after calling `server_restart`:

1. Try calling any tool again once or twice - some MCP clients retry/reinit
   transparently on error.
2. If that doesn't help, toggle the `apple-calendar` connector off and
   back on in Claude Desktop's settings. This does **not** require quitting
   the app, and forces a fresh `initialize` on a fresh subprocess.
3. Quitting and reopening Claude Desktop always works as a last resort, but
   defeats the purpose of this tool.

If you find that Claude Desktop handles this gracefully with no manual
step, or that it hangs instead of erroring, update this section.

#### `server_stop`

`server_stop` is `server_restart` without the relaunch: same brief-delay-
then-flush pattern, but it calls `os._exit(0)` instead of `os.execv`, so
the process just terminates. We verified directly against the raw MCP
client that:

- The process fully exits (confirmed via `ps -p <pid>` returning nothing).
- Any subsequent tool call on that session fails immediately with a
  `ClosedResourceError` (the stdio pipe is gone) - there's no ambiguity
  about whether it worked.

Nothing restarts it automatically. To resume using Calendar/Reminders
tools afterward, toggle the `apple-calendar` connector off and back on in
Claude Desktop (spawns a fresh subprocess), or restart Claude Desktop.
Use this when you want to pause the server's access to your data (e.g.
stepping away) without editing config files.

## Notes

- All data stays on-device; the server only talks to EventKit over stdio to
  the MCP client.
- Items created by this server get a `"Created by Claude Desktop"` line
  prepended to their notes, so you can tell them apart from items you
  created by hand.
- Dates in/out are ISO 8601 (`2026-03-15T14:00:00`), interpreted in the
  local timezone.
- Every tool catches its own exceptions and returns a
  `{"success": false, "error": ..., "message": ...}` dict instead of
  raising - a bad id, bad date, or missing permission never crashes the
  server.

## Development

```bash
uv run python -m apple_calendar_mcp.server   # run standalone (reads/writes stdio)
uv sync                                       # after editing pyproject.toml
```

To inspect tools interactively with the official MCP Inspector (requires
Node.js, not installed when this project was built):

```bash
npx @modelcontextprotocol/inspector uv run python -m apple_calendar_mcp.server
```

We validated the protocol layer with the `mcp` Python SDK's own client
(`ClientSession` + `stdio_client`) instead, since Node wasn't available:
full `initialize` handshake, `list_tools` (28 tools), and representative
tool calls (including error paths - invalid dates, invalid spans, unknown
ids, invalid priorities/scopes) all returned well-formed responses without
the server crashing. Tag rename/merge/delete correctness (updates only
matching items, preserves notes body, doesn't touch unrelated tags) was
verified with a fake in-memory store standing in for EventKit, since real
verification needs granted Calendar/Reminders permissions on this machine
first.
