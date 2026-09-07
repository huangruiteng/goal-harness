"""A settled position and its last applied digest are separate cursor facts."""

from __future__ import annotations

import json
from pathlib import Path
import select
import subprocess

import pytest

from shadow_e2e_fixture import REPO, ShadowWorkspace, workspace
from loopx.control_plane.coordination import local_authority_shadow_adapter as adapter
from loopx.control_plane.coordination import local_authority_shadow_outbox as outbox
from loopx.control_plane.coordination.coordination_state_contract_generated import TASK_LEASE_ACQUIRE_REQUEST_SCHEMA
from loopx.control_plane.work_items.task_lease_acquire_adapter import task_lease_acquire_authority_facts

pytestmark = pytest.mark.stage2c_e2e

# Pause only the actual primary rename, after durable prepare. No result is replaced.
LEASE_WORKER = r"""
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
const input = JSON.parse(process.argv[1]);
const rename = fs.promises.rename;
fs.promises.rename = async (source, target) => {
  if (String(target) === input.stop_before) {
    process.stdout.write('BARRIER primary-rename\n');
    await new Promise(resolve => setTimeout(resolve, 40000));
    throw new Error('parent did not terminate the paused writer');
  }
  return await rename(source, target);
};
syncBuiltinESMExports();
const {executeTaskLeaseAcquire} = await import(input.module);
process.stdout.write(JSON.stringify(await executeTaskLeaseAcquire(input.request)) + '\n');
"""


def acquire(w: ShadowWorkspace, todo: str, *, crash: bool = False) -> None:
    lease = w.runtime / 'goals' / w.goal / 'task-leases' / f'{todo}.json'
    request = {
        'schema_version': TASK_LEASE_ACQUIRE_REQUEST_SCHEMA,
        'runtime_root': str(w.runtime), 'goal_id': w.goal, 'todo_id': todo,
        'owner': 'agent-a', 'idempotency_key': f'acquire-{todo}',
        'ttl_seconds': 3600, 'write_scopes': [], 'expected_version': None,
        'authority': task_lease_acquire_authority_facts(
            registry_path=w.registry, goal_id=w.goal, todo_id=todo),
    }
    args = ['node', '--no-warnings', '--experimental-strip-types', '--input-type=module', '-e',
            LEASE_WORKER, json.dumps({'request': request, 'stop_before': str(lease) if crash else None,
            'module': (REPO / 'loopx/control_plane/work_items/task_lease_acquire.ts').as_uri()})]
    if not crash:
        result = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=30, check=True)
        assert json.loads(result.stdout)['acquired'] is True, result.stdout
        assert json.loads(lease.read_bytes())['owner'] == 'agent-a'
        return
    child = subprocess.Popen(args, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout is not None
        assert select.select([child.stdout], [], [], 30)[0], 'native writer missed primary rename'
        assert child.stdout.readline().strip() == 'BARRIER primary-rename'
        child.kill()
        child.communicate(timeout=10)
        assert child.returncode == -9
        assert not lease.exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)


@pytest.mark.parametrize('partition', ['todos', 'leases'])
@pytest.mark.parametrize('prior_mutations', [0, 1])
@pytest.mark.parametrize('abandoned', [1, 2])
def test_abandoned_cursor_survives_all_consumers(
    tmp_path: Path, partition: str, prior_mutations: int, abandoned: int,
) -> None:
    w = workspace(tmp_path, bootstrap=False)
    # A nonempty baseline must still have no applied-mutation digest.
    ids = [w.add(f'Baseline task {index}')['todo_id'] for index in range(3)]
    assert w.cli('coordination-shadow', 'bootstrap', '--execute')['bootstrap']['status'] == 'applied'

    def mutate(index: int) -> None:
        if partition == 'todos':
            ids.append(w.add(f'Applied task {index}')['todo_id'])
        else:
            acquire(w, ids[index])
        assert w.drain()['ok'] is True

    for index in range(prior_mutations):
        mutate(index)
    before = w.state.read_bytes()
    for index in range(abandoned):
        if partition == 'todos':
            w.crash('before_replace', 'todo', 'add', '--role', 'agent', '--text', f'Never applied {index}')
        else:
            acquire(w, ids[prior_mutations], crash=True)
        assert w.state.read_bytes() == before
        recovered = w.drain()
        assert recovered['ok'] is True and recovered['no_op'] == 1, recovered
        inspected = w.cli('coordination-shadow', 'inspect', success=False)['inspection']
        assert inspected['status'] == 'matched', inspected
        assert inspected['evidence']['operation_count'] == prior_mutations

    directory = outbox.partition_directory(w.runtime, w.goal, partition)
    path = directory / 'drain-cursor.json'
    cursor = json.loads(path.read_bytes())
    assert cursor['last_seq'] == prior_mutations + abandoned
    assert (cursor['last_partition_digest'] is None) == (prior_mutations == 0)
    assert w.drain()['outcome'] == 'nothing_pending'
    # Legitimate cursor loss reconstructs the same facts from real history.
    path.unlink()
    assert w.drain()['ok'] is True
    restored = json.loads(path.read_bytes())
    assert {k: v for k, v in restored.items() if k != 'updated_at'} == {
        k: v for k, v in cursor.items() if k != 'updated_at'}
    assert w.cli('coordination-shadow', 'inspect')['inspection']['status'] == 'matched'
    early = w.cli('coordination-shadow', 'qualify', success=False)['qualification']
    assert early['qualified'] is False and early['evidence']['operation_count'] == prior_mutations
    early_read = w.cli('coordination-shadow', 'read-candidate', '--todo-id', ids[-1], success=False)
    assert early_read['read_candidate']['read_candidate_qualified'] is False
    for index in range(prior_mutations, 3):
        mutate(index)
    qualified = w.cli('coordination-shadow', 'qualify')['qualification']
    assert qualified['qualified'] is True and qualified['scope'] == 'bounded', qualified
    assert qualified['evidence']['operation_count'] == 3
    assert qualified['sustained_parity_verdict'] == 'not_evaluated'
    transactions = adapter.read_local_authority_shadow(
        runtime_root=w.runtime, goal_id=w.goal, scan_limit=100,
    )['proof']['transactions']
    assert len(transactions) == 4 + abandoned
    assert [tx['receipts'][0]['seq'] for tx in transactions[1:]] == list(range(1, 4 + abandoned))
    assert sum(tx['receipts'][0]['no_op'] is True for tx in transactions[1:]) == abandoned
    candidate = w.cli('coordination-shadow', 'read-candidate', '--todo-id', ids[-1])
    assert candidate['read_candidate']['read_candidate_qualified'] is True, candidate


@pytest.mark.parametrize('partition', ['todos', 'leases'])
@pytest.mark.parametrize('applied', [False, True])
def test_forged_applied_digest_holds_every_consumer_without_rewriting_bytes(
    tmp_path: Path, partition: str, applied: bool,
) -> None:
    import hashlib

    w = workspace(tmp_path, bootstrap=False)
    todo = w.add('Baseline is not mutation coverage')['todo_id']
    w.cli('coordination-shadow', 'bootstrap', '--execute')
    if applied:
        if partition == 'todos':
            w.add('Real mutation with an applied digest')
        else:
            acquire(w, todo)
    elif partition == 'todos':
        w.crash('before_replace', 'todo', 'add', '--role', 'agent', '--text', 'Abandoned')
    else:
        acquire(w, todo, crash=True)
    assert w.drain()['ok'] is True
    view = adapter.read_local_authority_shadow(runtime_root=w.runtime, goal_id=w.goal, scan_limit=20)
    projection = view['proof']['transactions'][-1]['projection']
    fields = ('handoff_mode', 'todos') if partition == 'todos' else ('leases',)
    snapshot = {key: projection[key] for key in fields}
    snapshot_digest = 'sha256:' + hashlib.sha256(json.dumps(
        snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    path = outbox.partition_directory(w.runtime, w.goal, partition) / 'drain-cursor.json'
    cursor = json.loads(path.read_bytes())
    cursor['last_partition_digest'] = None if applied else snapshot_digest
    path.write_text(json.dumps(cursor, indent=3) + '\n')
    # Exact raw bytes matter even when all the cursor's identity fields are valid.
    # Lock diagnostics change and dead writer locks are reclaimed; authority evidence does not.
    before = {p.relative_to(w.runtime): p.read_bytes() for p in w.runtime.rglob('*')
              if p.is_file() and not p.name.endswith('.lock')}
    for command, key in [('inspect', 'inspection'), ('qualify', 'qualification'), ('read-candidate', 'read_candidate')]:
        args = ('--todo-id', todo) if command == 'read-candidate' else ()
        result = w.cli('coordination-shadow', command, *args, success=False)[key]
        assert result.get('reason_code') == 'outbox_cursor_unproved', result
    result = w.drain()
    assert result['ok'] is False and result['reason_code'] == 'outbox_cursor_unproved', result
    after = {p.relative_to(w.runtime): p.read_bytes() for p in w.runtime.rglob('*')
             if p.is_file() and not p.name.endswith('.lock')}
    assert after == before
