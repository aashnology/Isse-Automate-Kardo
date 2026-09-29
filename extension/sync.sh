#!/bin/sh
# The panel needs its own copy of the intent router (an extension can't load
# scripts from localhost). tests/test_extension.py fails if the copy drifts.
cp "$(dirname "$0")/../web/static/intents.js" "$(dirname "$0")/intents.js"
