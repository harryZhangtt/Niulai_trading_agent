#!/usr/bin/env bash
# Adapted from OthmanAdi/planning-with-files check-complete.sh, MIT.
# Read-only phase-format validation only. No hooks, auto-resolution or stop gate.
# Format success is NOT evidence that the work is complete.
set -eu
if [ "$#" -ne 1 ]; then
    echo "Usage: bash validate-plan.sh /absolute/workspace/path/task_plan.md" >&2
    exit 2
fi
case "$1" in
    /*) PLAN_FILE="$1" ;;
    *) echo "Pass an explicit absolute plan path." >&2; exit 2 ;;
esac
if [ ! -f "$PLAN_FILE" ]; then
    echo "Plan file not found." >&2
    exit 2
fi
awk '
        function finish_phase() {
            if (in_phase && statuses != 1) invalid = 1
        }
        /^### Phase([ \t]|$)/ {
            finish_phase()
            phases++
            in_phase = 1
            statuses = 0
        }
        !/^### Phase([ \t]|$)/ && /^#[ \t]|^##[ \t]|^###[ \t]/ {
            finish_phase()
            in_phase = 0
        }
        in_phase {
            line = $0
            statuses += gsub(/\*\*Status:\*\*[ \t]+(pending|in_progress|complete)([^[:alnum:]_]|$)/, "&", line)
            line = $0
            statuses += gsub(/\[(pending|in_progress|complete)\]/, "&", line)
        }
        END {
            finish_phase()
            if (!phases || invalid) {
                print "[planning-with-files] Plan format invalid: use ### Phase headings with exactly one native status per phase."
                exit 1
            }
            printf "[planning-with-files] Plan format valid (%d phases).\n", phases
        }
    ' "$PLAN_FILE"
