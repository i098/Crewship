#!/usr/bin/env bash
# Idle check of a shared Kubernetes cluster (docs/cloudflare-runner.md#fill-a-shared-cluster). Read-only: it
# changes nothing and never talks to the cluster; the dispatcher pipes in `kubectl get nodes,pods,jobs -A -o json`.
#
# Usage: kvz-idle-check.sh <node> <namespace> <max_jobs> <cpu_pct> <mem_pct> < snapshot.json
# Prints `FREE` and exits 0 only when one more job of ours may start on <node>. Anything else, including
# unreadable input, prints a reason and exits non-zero, and the dispatcher then uses this host instead.
set -uo pipefail
node=${1:?node}; ns=${2:?namespace}; max=${3:?max_jobs}; cpu_max=${4:?cpu_pct}; mem_max=${5:?mem_pct}

verdict=$(jq -r --arg n "$node" --arg ns "$ns" --argjson max "$max" --argjson cpu "$cpu_max" --argjson mem "$mem_max" '
  def cpu: if . == null then 0 elif endswith("m") then (.[:-1] | tonumber) else (tonumber * 1000) end;
  def mem: if . == null then 0
    elif endswith("Gi") then (.[:-2] | tonumber * 1024) elif endswith("Mi") then (.[:-2] | tonumber)
    elif endswith("Ki") then (.[:-2] | tonumber / 1024) else (tonumber / 1048576) end;
  def finished: .status.completionTime != null or ((.status.conditions // []) | any(.type == "Failed" and .status == "True"));
  (.items | map(select(.kind == "Node" and .metadata.name == $n)) | first) as $nd
  | (.items | map(select(.kind == "Pod"))) as $pods
  | ($pods | map(select(.spec.nodeName == $n and (.status.phase == "Running" or .status.phase == "Pending")))) as $on
  | (.items | map(select(.kind == "Job" and .metadata.namespace == $ns and (finished | not))) | length) as $active
  | if $nd == null then ["node missing"] else [
      (if ($nd.status.conditions | map(select(.type == "Ready") | .status) | first) != "True" then "node not Ready" else empty end),
      ($nd.status.conditions[]? | select((.type == "DiskPressure" or .type == "MemoryPressure" or .type == "PIDPressure") and .status == "True") | "pressure " + .type),
      ($pods[] | select(.status.phase == "Pending" and .metadata.namespace != $ns and .metadata.deletionTimestamp == null
          and ((.spec.nodeName // "") == $n or (.spec.nodeName // "") == "")) | "other pod pending: " + .metadata.namespace + "/" + .metadata.name),
      (if $active >= $max then "\($active) of \($max) own jobs active" else empty end),
      (([$on[].spec.containers[].resources.requests.cpu | cpu] | add // 0) as $c | (($nd.status.allocatable.cpu | tonumber) * 1000) as $a
        | if $c * 100 / $a > $cpu then "cpu requested \($c)m of \($a)m, over \($cpu)%" else empty end),
      (([$on[].spec.containers[].resources.requests.memory | mem] | add // 0) as $m | ($nd.status.allocatable.memory | mem) as $a
        | if $m * 100 / $a > $mem then "memory requested \($m | floor)Mi of \($a | floor)Mi, over \($mem)%" else empty end)
    ] end
  | if length == 0 then "FREE" else "BUSY: " + join("; ") end') || { echo "BUSY: unreadable snapshot"; exit 2; }
echo "$verdict"
[ "$verdict" = FREE ]
