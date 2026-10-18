#!/bin/bash
# Installe MIR dans .venv : Python 3.12 et les versions exactes de uv.lock. Nécessite uv (https://docs.astral.sh/uv/).
# Ensuite : uv run mir
cd "$(dirname "$0")" && uv sync
