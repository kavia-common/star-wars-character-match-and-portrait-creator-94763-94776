#!/bin/bash
cd /home/kavia/workspace/code-generation/star-wars-character-match-and-portrait-creator-94763-94776/character_generator_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

