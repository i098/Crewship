#!/usr/bin/env bash
# Run the database service tests without access to the host Docker daemon.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
lab="crewship-postgres-test-$$"
docker=(docker)
if [ ! -w /var/run/docker.sock ]; then docker=(sudo -n docker); fi
trap '"${docker[@]}" rm -f "$lab" >/dev/null 2>&1 || true' EXIT
"${docker[@]}" run --detach --rm --privileged --name "$lab" \
  --env DOCKER_TLS_CERTDIR= --volume "$root:/src:ro" \
  docker:dind --storage-driver=vfs >/dev/null
"${docker[@]}" exec "$lab" sh -ec '
  timeout 90 sh -c "until docker info >/dev/null 2>&1; do sleep 1; done"
  apk add --no-cache python3 py3-pip bash nodejs postgresql-client
  python3 -m venv /lab-venv
  /lab-venv/bin/pip install uv
  UV_PROJECT_ENVIRONMENT=/lab-venv /lab-venv/bin/uv sync --locked --group dev --project /src
  export PATH=/lab-venv/bin:$PATH CREWSHIP_POSTGRES_LAB=1
  python -m pytest -q -p no:cacheprovider /src/tests/test_project_databases.py /src/tests/test_removed_backend.py /src/tests/test_fleet_units.py /src/tests/test_configuration.py /src/tests/test_provisions.py /src/tests/test_readme.py
  ansible-playbook -i /src/blueprint/ansible/inventory.yml /src/blueprint/ansible/site.yml --syntax-check
'
