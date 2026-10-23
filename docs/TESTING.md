# Testing guide for judges

Isse Automate Kardo (Hexi) is an Alexa+ track entry: a self-hosted MCP server
over Streamable HTTP plus a web front end that talks to it.

## Project testing link

There is no hosted instance. The project runs locally in about three minutes,
which keeps your review independent of any server we would have to keep alive.

- Repository: https://github.com/aashnology/Isse-Automate-Kardo
- Web page once running: http://127.0.0.1:5000
- MCP endpoint once running: http://127.0.0.1:8000/mcp

## Credentials

None. No account, API key, or login is needed. Every variable in
`.env.example` is optional, and the project runs with none of them set.

## Requirements

Python 3.11 or 3.12 and git. The Docker image uses Python 3.12.

## Run it

macOS / Linux:

```bash
git clone https://github.com/aashnology/Isse-Automate-Kardo.git
cd Isse-Automate-Kardo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/mcp_server.py      # terminal 1
python web/server.py          # terminal 2
```

Windows PowerShell: the same, but activate with `.venv\Scripts\activate`.

Open http://127.0.0.1:5000. The title bar shows the build id of the code being
served; it should match `git log -1 --format=%h`.

With Docker instead: `docker compose up --build`, then open
http://localhost:5000.

## Five-minute walkthrough (built-in sample data)

Type each line into the chat box under the Hexi panel. The sample dataset is
synthetic, generated deterministically on first start.

| Type | Expected answer |
|---|---|
| `brief me` | Biggest time sink is `bug_triage` at 24.1 hours, rated partially automatable, with one unusually long run. |
| `why is bug triage slow` | `reproduce_attempt` takes the biggest share, 42% of the total time. |
| `what can I automate` | Starts with `weekly_reporting`, saving about 0.41 hours a week. |
| `automate the reporting steps` | Proposes automating `column_cleanup`, `upload`, `export`, `file_download` and `rename` (about 22.3 minutes saved per run), then confirms: reliability 89 out of 100, grade A. |
| `automate bug triage` | Declines: no steps in that workflow are safe to automate without human judgment. |

Nothing executes until you ask. On the API level, `propose_automation` and
`confirm_automation` are separate tools, and a confirmation is single-use.

## Your own data

Open the **My data** tab. Paste the contents of `examples/sales_report_steps.txt`
into the step-list box and click **Analyze this**. Expected: 60 events and 2
discovered patterns. Then type `what can I automate` and `automate it`. For the
sales-report workflow, Hexi reports about 28.7 minutes saved per run (roughly
2.54 hours a week), reliability 79 out of 100, grade B.

ActivityWatch JSON and Toggl CSV exports are also accepted. The GitHub-repo and
Google Sheet / Drive link imports fetch public data and need internet access.

## Verify the MCP server directly

The server must negotiate protocol 2025-11-25 over Streamable HTTP.

```bash
curl -s -i -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"judge","version":"1.0"}}}'
```

Expected: HTTP 200, an `mcp-session-id` header, and `"protocolVersion":"2025-11-25"`
in the event-stream body. To list the tools and call one with the official
Python client (installed by `requirements.txt`):

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client("http://127.0.0.1:8000/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            print("protocol:", init.protocolVersion)
            tools = await s.list_tools()
            print(len(tools.tools), "tools:", ", ".join(t.name for t in tools.tools))
            res = await s.call_tool("get_top_friction_points", {})
            print(res.content[0].text[:200])

asyncio.run(main())
```

Expected: `protocol: 2025-11-25` and 16 tools, starting with
`discover_workflows` and including `propose_automation` and `confirm_automation`.

## Automated tests

```bash
pytest
```

Expected: 246 passed. Run the tests with the servers stopped. Some tests talk
to a running MCP server, and doing so while your own demo is up can write
dismissals into `data/user_memory.json` and change what the sample shows. If
that happens, stop both servers and delete `data/user_memory.json` and the
`data/workspaces/` folder; both are gitignored.

## What is simulated

- The Echo device is simulated. The browser microphone and the
  "Alexa, ask Hexi..." wake phrase stand in for it, and typing a command works
  the same way. Voice needs Chrome and microphone permission, so typing is the
  more reliable way to test.
- The MCP server, the Streamable HTTP transport, and every tool call are real.
- The sample data is synthetic, not a recording of a real person's activity.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Address already in use" or old behaviour after updating | An old server still holds the port | Windows: `netstat -ano \| findstr :5000`, then `taskkill /PID <pid> /F`. macOS/Linux: `lsof -i :5000`, then `kill <pid>`. Repeat for port 8000. |
| Page loads but replies fail | The MCP server is not running | Start `python src/mcp_server.py` in its own terminal. |
| A sample workflow is missing | It was dismissed earlier | Delete `data/user_memory.json` and restart. |
