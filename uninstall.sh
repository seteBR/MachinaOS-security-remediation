#!/usr/bin/env bash
# MachinaOS Uninstaller
#
# Usage: curl -fsSL https://raw.githubusercontent.com/zeenie-ai/MachinaOS/main/uninstall.sh | bash

set -e

echo "Uninstalling MachinaOS..."
echo ""

# Uninstall machinaos npm package
if npm list -g machinaos &> /dev/null; then
  npm uninstall -g machinaos
  echo "machinaos removed"
else
  echo "machinaos not installed"
fi

echo ""
echo "Done!"
echo ""
