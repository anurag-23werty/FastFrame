#!/bin/sh
set -eu

if [ "${FASTFRAME_QUIET:-0}" != "1" ]; then
    printf '%s\n' \
        '      .-~~~-.' \
        '  .- ~ ~-(       )_ _' \
        ' /                 ~ -.' \
        '|       DOCKER          |' \
        ' \\                 .-~~-.' \
        '   ~- ._ _ _.-~       ~-.' \
        ' FastFrame container ready 🚀'
fi

exec fastframe "$@"
