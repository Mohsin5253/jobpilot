#!/usr/bin/env bash
# Build dist/Flowtype.app. Run from the flowtype/ folder in the project's venv.
set -euo pipefail
pip install -e ".[dev,package]"
cd packaging
pyinstaller --noconfirm --distpath ../dist --workpath ../build flowtype.spec
echo "Built dist/Flowtype.app. Grant it Microphone, Input Monitoring and Accessibility on first launch."
