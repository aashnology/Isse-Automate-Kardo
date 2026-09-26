"""
Server-side narration via Amazon Bedrock -- the AWS Builder piece of this
project, and the "Bedrock narration" line the README used to list as
future work.

Why this exists, and why it's server-side rather than left to Alexa+:
every other tool in this project returns structured data (numbers, step
breakdowns, cluster ids) on purpose -- see friction_radar.py and
workflow_discovery.py's own docstrings on keeping scoring and clustering
deterministic and LLM-free. But stitching *several* tool outputs into one
coherent spoken briefing ("here's what's costing you time, and here's the
one thing that looked unusual this week") is a genuine language-generation
task, not a scoring decision, and doing it once on the server means Alexa+
gets a single ready-to-speak paragraph instead of having to reason over
three separate JSON payloads itself. The distinction that matters: Bedrock
composes phrasing over numbers we already computed deterministically. It
never decides what's important, ranks anything, or invents a figure -- the
prompt hands it the finished analysis and tells it to phrase it, nothing
more.

Gated behind ENABLE_BEDROCK_NARRATION so the rest of the server (and the
existing MCP tools) work identically with or without AWS credentials
configured -- important for anyone cloning this repo to try it without
first setting up an AWS account.
"""

import json
import os

ENABLED = os.environ.get("ENABLE_BEDROCK_NARRATION", "false").lower() == "true"
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")

_SYSTEM_PROMPT = (
    "You narrate workflow-automation findings for a voice assistant (Alexa+) "
    "to speak aloud. You are given already-computed analysis as JSON -- "
    "friction points, time costs, root causes, anomalies. Turn it into 2-4 "
    "spoken sentences: plain, direct, no filler, no bullet points, no "
    "restating numbers the user didn't ask for. Never invent a number, "
    "workflow name, or step that isn't in the JSON you were given."
)


class BedrockNarrator:
    """Thin wrapper around the Bedrock Converse API. Falls back to a
    deterministic template (no network call, no AWS dependency) whenever
    Bedrock is disabled, unreachable, or the call errors -- narration is a
    nice-to-have on top of the real analysis, never a point of failure for
    it."""

    def __init__(self, enabled=None, model_id=None, region=None):
        self.enabled = ENABLED if enabled is None else enabled
        self.model_id = model_id or MODEL_ID
        self.region = region or REGION
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def narrate(self, payload: dict, fallback: str) -> dict:
        """payload: the already-computed analysis dict to phrase.
        fallback: the deterministic, template-based sentence to use if
        Bedrock is off or the call fails. Always returns a dict with a
        `narration` string and a `source` field so callers (and the demo)
        can show exactly which path produced the sentence."""
        if not self.enabled:
            return {"narration": fallback, "source": "template"}

        try:
            client = self._get_client()
            response = client.converse(
                modelId=self.model_id,
                system=[{"text": _SYSTEM_PROMPT}],
                messages=[{
                    "role": "user",
                    "content": [{"text": json.dumps(payload, default=str)}],
                }],
                inferenceConfig={"maxTokens": 200, "temperature": 0.3},
            )
            text = response["output"]["message"]["content"][0]["text"].strip()
            return {"narration": text, "source": f"bedrock:{self.model_id}"}
        except Exception as exc:  # noqa: BLE001 -- narration must never crash a tool call
            return {
                "narration": fallback,
                "source": "template",
                "bedrock_error": str(exc),
            }
