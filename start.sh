#!/bin/bash
# Arch V3 bot — start script for PandaStack Apps
pip install -r requirements.txt >/dev/null 2>&1
# restore private env if bundled privately (kept out of git normally)
if [ -f .env.private ]; then cp .env.private .env; fi
mkdir -p logs sessions cache/cards
python snoser.py
