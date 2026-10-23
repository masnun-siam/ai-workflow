#!/bin/sh
# Block until an aiw session stops running or asks a question; print its state.
# usage: wait-session.sh SESSION_ID [port]
id=$1; port=${2:-8431}
while :; do
  s=$(curl -s "http://127.0.0.1:$port/api/sessions/$id" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["outcome"], "question" if d.get("pending_question") else "")')
  case "$s" in running|"running "|starting*|queued*) sleep 20 ;; *) echo "$s"; exit 0 ;; esac
done
