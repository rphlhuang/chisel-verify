#!/usr/bin/env bash
# Run the LTL capability probe end-to-end: emit CHIRRTL for every probe
# module, then lower + model-check each and print the classification table.
# Self-contained -- everything is created under this folder.
set -euo pipefail
cd "$(dirname "$0")"

sbt -batch "runMain probe.ProbeChirrtlMain"
bash formal_check.sh 0 'generated/chirrtl/*.fir'