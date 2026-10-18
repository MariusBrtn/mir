:: Installe MIR dans .venv : Python 3.12 et les versions exactes de uv.lock. Necessite uv (https://docs.astral.sh/uv/).
:: Ensuite : uv run mir
cd /d "%~dp0" && uv sync
