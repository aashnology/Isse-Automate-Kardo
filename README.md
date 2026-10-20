# Isse Automate Kardo

Meet Hexi, an Alexa+ MCP assistant that finds where your time goes, pinpoints the bottleneck step and says "Isse Automate Kardo." It remembers what you dismiss, so it never nags twice.

Built for Amazon's **Build, Ship, Shape** hackathon, **Alexa+ track**, with
an entry in the **Open Source** mini challenge.

Developer manual (PDF): [`docs/Isse-Automate-Kardo-Developer-Manual.pdf`](docs/Isse-Automate-Kardo-Developer-Manual.pdf)

## Quick start

![Quick start](docs/assets/panels/00-quick-start.png)

## Meet Hexi

![Meet Hexi](docs/assets/panels/01-meet-hexi.png)


## The journey

![The journey](docs/assets/panels/02-the-journey.png)

## How it's built

![How it's built](docs/assets/panels/03-how-its-built.png)

## Agent Skill

![Agent Skill](docs/assets/panels/04-agent-skill.png)

## Running it

![Running it: local and Docker](docs/assets/panels/05-running-it.png)

### Locally

The MCP server alone is enough for any MCP client (Alexa+, MCP Inspector).
Hexi's tabs, chat and voice ask the MCP server first. If it isn't running they
fall back to calling the same Python functions directly, so the page still
works; each API response has a `via` field (`mcp` or `direct`) saying which
answered. The extension needs the MCP server running.

Imported datasets live in a named Docker volume (`datasets`) shared by both
services, so the non-root container user can always write them. The services
were exercised outside Docker with the same environment variables the compose
file sets; the image itself has not been built in the authoring environment,
so the first `docker compose up --build` is the real test.

### Tests

![Tests](docs/assets/panels/06-tests.png)

## License

![License](docs/assets/panels/07-license.png)
