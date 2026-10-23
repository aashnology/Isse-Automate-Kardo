# Friction log

Friction hit while building Hexi on the MCP Python SDK (`mcp==1.30.0`,
FastMCP server and Streamable HTTP client), the Alexa+ MCP integration path,
and Docker Compose. Each entry names where to see it in this repository.

## 1. DNS-rebinding protection is silently off for any non-loopback host

- **Task attempted:** run the MCP server inside a Docker container, which
  requires binding to `0.0.0.0` rather than `127.0.0.1`.
- **Steps taken:** set the FastMCP host to `0.0.0.0`, read
  `mcp/server/transport_security.py` in the installed 1.30.0 SDK to see what
  protection the server had in that configuration.
- **Expected:** the SDK keeps DNS-rebinding and Origin protection enabled, or
  at least warns when it is off.
- **Actual:** protection is enabled automatically only when the host is exactly
  `127.0.0.1`, `localhost` or `::1`. For any other host, including `0.0.0.0`,
  it defaults to off with no warning.
- **Severity:** High. It is a security default that fails silently, and the
  Docker use case hits it immediately.
- **Workaround:** the server defaults to a loopback bind. A wider bind is an
  explicit opt-in and refuses to start unless `MCP_ALLOWED_HOSTS` and
  `MCP_ALLOWED_ORIGINS` are set, in which case we build
  `TransportSecuritySettings` ourselves.
- **Suggestion:** log a warning, or require an explicit opt-out, when the host
  is non-loopback and no `TransportSecuritySettings` was supplied. Document the
  rule in the Streamable HTTP deployment guide, with a Docker example.
- **Where to see it:** `src/mcp_server.py` (the comment block above
  `FastMCP(...)`), commit `822d0ea`.

## 2. No built-in way to require a minimum protocol version

- **Task attempted:** guarantee the web front end only ever talks to the MCP
  server over spec 2025-11-25 or later, the hackathon minimum.
- **Steps taken:** connected with `streamable_http_client` and
  `ClientSession.initialize()`, then looked for a client option to refuse older
  versions.
- **Expected:** a client setting such as a minimum protocol version.
- **Actual:** `initialize()` returns whatever version the server negotiated and
  the client carries on, so a downgrade would run unnoticed.
- **Severity:** Low. It is easy to guard, but easy to forget.
- **Workaround:** `web/mcp_bridge.py` compares `protocolVersion` to
  `MIN_PROTOCOL = "2025-11-25"` after `initialize()` and raises
  `McpUnavailable` if the server is older.
- **Suggestion:** add a `min_protocol_version` argument to the client session,
  or expose the supported versions so callers can pin them.
- **Where to see it:** `web/mcp_bridge.py` (the guard); `tests/test_mcp_protocol.py`
  asserts the server negotiates 2025-11-25 or later.

## 3. Secure loopback default makes a containerised web service unreachable

- **Task attempted:** run the whole project with `docker compose up --build`
  and open the Hexi page from the host.
- **Steps taken:** reviewed the compose file against the server's bind
  settings. The MCP service had an explicit non-loopback bind, but the web
  service did not.
- **Expected:** the mapped port `127.0.0.1:5000:5000` reaches the web page.
- **Actual:** the web server defaults to binding `127.0.0.1` inside the
  container, which Docker's port mapping cannot reach, so the page would not
  open even though the container is running. Nothing reports an error.
- **Severity:** Medium. The Docker route looks fine and fails silently, so a
  judge would see a dead page.
- **Workaround:** set `WEB_BIND_HOST: "0.0.0.0"` on the web service in
  `docker-compose.yml`; the host mapping stays loopback-only.
- **Suggestion:** the Streamable HTTP and FastMCP docs should say plainly that
  loopback defaults need an explicit bind override in containers, and show the
  matching compose snippet. A startup log line stating the bound address would
  also have exposed this at once.
- **Where to see it:** `docker-compose.yml`, commit `48c7062`.

## 4. Hand-testing a Streamable HTTP server is awkward without an inspector

- **Task attempted:** write judge-facing instructions to check the MCP server
  using only `curl` or a few lines of code.
- **Steps taken:** posted an `initialize` request with curl, then tried to
  follow it with `tools/list`.
- **Expected:** a plain JSON response I can read directly.
- **Actual:** the response comes back as `text/event-stream` (`event: message`
  framing), the request must accept both `application/json` and
  `text/event-stream`, and the session id arrives in an `mcp-session-id`
  response header that later requests would need.
- **Severity:** Low. It works, but a newcomer cannot read the output easily.
- **Workaround:** `docs/TESTING.md` uses curl only for the handshake and then
  switches to a short script with the official Python client, which handles
  sessions.
- **Suggestion:** add a short curl cookbook to the MCP docs covering the
  required headers and session handling, and a one-line CLI command that
  prints the tool list of a Streamable HTTP server.
- **Where to see it:** `docs/TESTING.md`, "Verify the MCP server directly".
