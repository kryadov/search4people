#!/usr/bin/env bash
if [ ! -f .venv/bin/activate ]; then
  python3.13 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt
python -m src.app