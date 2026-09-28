# Submission materials

Drafts for the Devpost fields that aren't the code or the video. Written
from what was actually done and observed while building, including what was
*not* done -- judges read these next to the repo, so anything claimed here
should be checkable there.

---

## Product feedback

### Tools, APIs and SDKs used, and for what

- **MCP Python SDK (`mcp==1.30.0`, FastMCP)** -- the server itself: 13 tools
  over Streamable HTTP. Verified with a real MCP client in
  `tests/test_mcp_protocol.py` (negotiates protocol `2025-11-25`, lists the
  tools, executes a call).
- **Amazon Bedrock (Converse API via boto3)** -- one optional tool,
  `narrate_briefing`. **Written and reviewed but never run against a live AWS
  account** (see friction log); the template fallback path is what's tested.
- **GitHub REST API** -- read-only PR-history import for the Orbi demo. Not
  an Amazon tool; listed for completeness.

### What worked well

- **FastMCP's developer experience.** Decorating a typed function with
  `@mcp.tool()` and letting the docstring become the tool description is the
  right abstraction: 13 tools with almost no protocol boilerplate. Writing
  docstrings as instructions to the calling model ("use this when the user
  asks...") turned out to be a genuinely useful design discipline, because
  the docstring *is* the interface an assistant reasons over.
- **Protocol version negotiation was unambiguous.** Reading
  `LATEST_PROTOCOL_VERSION` in the installed package and seeing the client
  negotiate `2025-11-25` made the track's version requirement checkable in
  one command, not a matter of trusting docs.
- **Streamable HTTP testability.** Because it's plain HTTP, a subprocess
  plus the SDK's own client is enough for a CI-safe end-to-end test. No
  emulator needed.
- **The track requirements were clearly written**, especially the explicit
  split between the real MCP path and the simulated-experience path, and the
  "obvious vs. creative" examples in the judging notes, which directly shaped
  what got built.

### What needs work

- **No way to try the server inside a real Alexa+ experience.** The
  materials say to build an MCP server, but point to no Alexa+ sandbox,
  emulator, or test harness. This project was verified against a generic MCP
  client only, and is *not* claimed to have been tested on Alexa+. An
  official "connect your MCP server to an Alexa+ test surface" walkthrough
  would be the single most useful addition for this track.
- **Deprecated client entry point.** `streamablehttp_client` still works but
  emits a deprecation warning pointing to `streamable_http_client`. The
  rename is drop-in, but examples and blog posts found by search still use
  the old name.
- **Loopback default.** `FastMCP` binds to 127.0.0.1 by default, so any
  containerized deployment needs an explicit `host="0.0.0.0"`. This was found
  by reading the constructor signature while writing the Dockerfile, not by
  hitting an error, and the Docker image itself has not been built or run in
  the environment this was developed in.
- **Version pinning.** PyPI currently lists `mcp` 2.x; this project stays on
  the 1.30.0 it verified. 2.x was not evaluated, so nothing here speaks to
  migration effort.

### Onboarding experience (zero to hello world)

MCP: fast. A working server with one tool is a few lines, and the SDK's own
client made the first end-to-end check easy. AWS/Bedrock: never reached hello
world, for the reason in the friction log below.

### Would we build with these again?

**MCP: yes, without hesitation** -- the abstraction is good and the open
standard means the work isn't locked to one assistant. **AWS: yes in
principle, but only once trying it doesn't require a payment card and
navigating a recently changed billing model as a student.**

### AWS services

Amazon Bedrock (Converse API), used by `narrate_briefing` to phrase
already-computed analysis into a spoken-ready summary, gated behind
`ENABLE_BEDROCK_NARRATION`. Bedrock never scores, ranks or touches raw data.
**Honest status: implemented with a tested deterministic fallback; not
exercised against live AWS.** The AWS Builder mini-challenge entry should be
read with that in mind.

---

## Friction log

### 1. Could not test Bedrock/SES without adding a payment card

- **Task attempted:** set up an AWS account to test Bedrock narration and an
  SES-backed "confirm automation" action.
- **Steps taken:** reviewed the Free Tier signup flow and current SES/Bedrock
  free-tier terms.
- **Expected:** a low-risk way to test one or two services for pennies of
  usage.
- **Actual:** a card is required for every signup. The free tier was
  restructured (July 2025) into a $100-200 signup-credit model, and SES's
  older recurring free allowance closed to new accounts in July 2026. The
  credit model is generous for this usage, but that only becomes clear after
  researching a recent billing-policy change -- a real deterrent for a
  cost-conscious student deciding whether to proceed at all.
- **Severity:** medium. Not a platform defect, but it keeps a segment of
  participants out of the AWS Builder mini-challenge despite negligible real
  cost.
- **Workaround:** built Bedrock narration with an honest, tested template
  fallback (off by default); deferred live testing.
- **Suggestion:** surface a card-free path in the hackathon's own AWS
  materials (e.g. a temporary sandbox with hackathon-scoped credentials).

### 2. No Alexa+ test surface for an MCP server

- **Task attempted:** confirm the server works from an Alexa+ client.
- **Steps taken:** searched the provided track materials for an emulator,
  sandbox or test harness.
- **Expected:** a documented way to point an Alexa+ test surface at a
  self-hosted MCP endpoint.
- **Actual:** none found; verified with a generic MCP client instead.
- **Severity:** medium-high for this track -- it is the difference between
  "conforms to the spec" and "works on the product."
- **Workaround:** protocol-level test against the real running server
  (`tests/test_mcp_protocol.py`), plus a browser demo (Orbi) that simulates
  the conversational experience. Neither is claimed to be Alexa+.
- **Suggestion:** an official test harness or a documented developer-mode
  connection flow.

### 3. Deprecated client name still dominates examples

- **Task attempted:** write a client-side integration test.
- **Actual:** `streamablehttp_client` worked but warned; the current name is
  `streamable_http_client`.
- **Severity:** low.
- **Workaround:** renamed (identical signature).
- **Suggestion:** update docs/examples to the current name and note the
  deprecation in the migration guide.

---

## Feature requests

- **Alexa+ developer-mode connection for self-hosted MCP servers** --
  *critical* for this track (see friction log #2).
- **Card-free hackathon sandbox for AWS services** -- *important* for
  student participation.
