#!/bin/bash
mkdir -p /var/log/retrophone

for f in /run/retrophone/*.log; do
  [ -e "$f" ] || continue
  base=$(basename "$f")
  cp "$f" "/var/log/retrophone/$base"
done
