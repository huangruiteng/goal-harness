"""Acceptance probes for the NoKV-backed LoopX provider. Run subcommands:
   python probes.py setup|p1|p2|p3|p4pre|p4post|p5|p6
Emits JSON lines to stdout (raw evidence)."""

import json
import os
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from provider import NoKVShadowProvider, sample_envelope, _derive_id

ROOT_ID = os.environ["NOKV_ROOT_ID"]
ETCD = os.environ.get("NOKV_ETCD", "http://127.0.0.1:2379")
S3_ENDPOINT = os.environ.get("NOKV_S3_ENDPOINT", "http://127.0.0.1:9000")
S3_BUCKET = os.environ.get("NOKV_S3_BUCKET", "nokv-loopx-e2e")
S3_KEY = os.environ.get("NOKV_S3_KEY", "minioadmin")
S3_SECRET = os.environ.get("NOKV_S3_SECRET", "minioadmin")
WORKBENCH = "loopx-authority"
GOAL = "ark-agent-loop-shared"
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_state.json")

from nokv import Client, RoutingConfig, ObjectStoreConfig  # noqa: E402


def new_client():
    return Client(
        ROOT_ID,
        RoutingConfig.etcd([ETCD], key_prefix=os.environ.get("NOKV_ETCD_PREFIX", "/nokv/control")),
        ObjectStoreConfig.s3(
            S3_BUCKET,
            endpoint=S3_ENDPOINT,
            access_key_id=S3_KEY,
            secret_access_key=S3_SECRET,
        ),
    )


def out(tag, **kw):
    print(json.dumps({"probe": tag, **kw}, sort_keys=True), flush=True)


def save_state(d):
    old = load_state()
    old.update(d)
    with open(STATE, "w") as f:
        json.dump(old, f)


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def cmd_setup():
    c = new_client()
    incarnation = "ab" * 16  # fixed => idempotent create
    res = c.create_workspace(WORKBENCH, workspace_incarnation_id=incarnation)
    out("setup", workspace=dict(res) if not isinstance(res, dict) else res)


def cmd_p1():
    c = new_client()
    p = NoKVShadowProvider(c, WORKBENCH, GOAL)
    doc, rev = p.load()
    out("p1.load", revision=rev, head_absent=doc is None)
    cid = str(uuid.uuid4())
    env = sample_envelope(command_id=cid, expected_revision=rev)
    t0 = time.perf_counter()
    receipt = p.compare_and_put(rev, cid, env)
    dt = (time.perf_counter() - t0) * 1000
    out("p1.claim", command_id=cid, receipt=receipt, latency_ms=round(dt, 2))
    doc2, rev2 = p.load()
    out("p1.verify", revision=rev2, head_command_id=doc2["command_id"],
        lease=doc2["lease"])
    save_state({"p1_command_id": cid, "p1_expected_revision": rev,
                "p1_new_revision": receipt.get("authority_revision")})


def cmd_p2():
    rounds = int(os.environ.get("P2_ROUNDS", "20"))
    workers = 8
    clients = [new_client() for _ in range(workers)]
    providers = [NoKVShadowProvider(c, WORKBENCH, GOAL) for c in clients]
    anomalies = 0
    for rnd in range(rounds):
        base_rev = providers[0].stat_revision()
        cids = [str(uuid.uuid4()) for _ in range(workers)]
        envs = [sample_envelope(command_id=cids[i], agent_id=f"agent-{i}",
                                device_id=f"dev-{i}", expected_revision=base_rev,
                                todo_id=f"todo-r{rnd}")
                for i in range(workers)]

        def run(i):
            t0 = time.perf_counter()
            r = providers[i].compare_and_put(base_rev, cids[i], envs[i])
            r["_latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            r["_worker"] = i
            return r
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(run, range(workers)))
        applied = [r for r in results if r["result"] == "applied"]
        conflicts = [r for r in results if r["result"] == "conflict"]
        already = [r for r in results if r["result"] == "already_applied"]
        conflicts_learned = [r for r in conflicts
                             if r.get("current_revision") == base_rev + 1]
        ok = (len(applied) == 1 and len(conflicts) == workers - 1
              and len(already) == 0
              and len(conflicts_learned) == len(conflicts))
        if not ok:
            anomalies += 1
            out("p2.round.ANOMALY", round=rnd, base_revision=base_rev,
                results=results)
        else:
            out("p2.round", round=rnd, base_revision=base_rev,
                applied=1, conflicts=len(conflicts),
                conflicts_learned_current_revision=len(conflicts_learned),
                winner_worker=applied[0]["_worker"],
                new_revision=applied[0]["authority_revision"])
    out("p2.summary", rounds=rounds, anomalies=anomalies)


def cmd_p3():
    st = load_state()
    cid = st["p1_command_id"]
    orig_expected = st["p1_expected_revision"]
    c = new_client()
    p = NoKVShadowProvider(c, WORKBENCH, GOAL)
    rev_before = p.stat_revision()
    env = sample_envelope(command_id=cid, expected_revision=orig_expected)
    receipt = p.compare_and_put(orig_expected, cid, env)
    rev_after = p.stat_revision()
    out("p3.retry", command_id=cid, original_expected_revision=orig_expected,
        receipt=receipt, revision_before=rev_before, revision_after=rev_after,
        generation_unchanged=rev_before == rev_after,
        no_double_apply=rev_after == rev_before)


def cmd_p3b():
    """Retry of the MOST RECENT winner with its original expected revision."""
    c = new_client()
    p = NoKVShadowProvider(c, WORKBENCH, GOAL)
    base = p.stat_revision()
    cid = str(uuid.uuid4())
    env = sample_envelope(command_id=cid, expected_revision=base,
                          todo_id="todo-p3b")
    first = p.compare_and_put(base, cid, env)
    rev_after_first = p.stat_revision()
    retry = p.compare_and_put(base, cid, env)  # crash-retry, same command_id
    rev_after_retry = p.stat_revision()
    out("p3b", first=first, retry=retry,
        revision_after_first=rev_after_first,
        revision_after_retry=rev_after_retry,
        no_double_apply=rev_after_first == rev_after_retry,
        lease_id_stable=first.get("lease_id") == retry.get("lease_id"))


def cmd_p4pre():
    c = new_client()
    p = NoKVShadowProvider(c, WORKBENCH, GOAL)
    rev = p.stat_revision()
    cid = str(uuid.uuid4())
    env = sample_envelope(command_id=cid, expected_revision=rev,
                          todo_id="todo-durability")
    receipt = p.compare_and_put(rev, cid, env)
    out("p4.pre", command_id=cid, receipt=receipt)
    save_state({"p4_command_id": cid,
                "p4_revision": receipt.get("authority_revision"),
                "p4_lease_id": receipt.get("lease_id")})


def cmd_p4post():
    st = load_state()
    c = new_client()
    p = NoKVShadowProvider(c, WORKBENCH, GOAL)
    doc, rev = p.load()
    out("p4.post", expected_revision=st["p4_revision"], loaded_revision=rev,
        expected_command_id=st["p4_command_id"],
        loaded_command_id=doc["command_id"],
        lease_id_match=doc["lease"]["lease_id"] == st["p4_lease_id"],
        intact=(rev == st["p4_revision"]
                and doc["command_id"] == st["p4_command_id"]))


def cmd_p5():
    n = int(os.environ.get("P5_N", "100"))
    c = new_client()
    p = NoKVShadowProvider(c, WORKBENCH, GOAL)
    cap_ms, load_ms = [], []
    unavailable_retries = 0
    for i in range(n):
        rev = p.stat_revision()
        cid = str(uuid.uuid4())
        env = sample_envelope(command_id=cid, expected_revision=rev,
                              todo_id=f"todo-p5-{i}")
        t0 = time.perf_counter()
        r = p.compare_and_put(rev, cid, env)
        while r["result"] == "unavailable":
            unavailable_retries += 1
            time.sleep(0.1)
            r = p.compare_and_put(rev, cid, env)
        cap_ms.append((time.perf_counter() - t0) * 1000)
        assert r["result"] in ("applied", "already_applied"), r
        if r["result"] != "applied" or r.get("replayed"):
            out("p5.nonclean_apply", i=i, receipt=r)
        t0 = time.perf_counter()
        doc, rev2 = p.load()
        load_ms.append((time.perf_counter() - t0) * 1000)
        if r.get("authority_revision") is not None:
            assert rev2 == r["authority_revision"], (rev2, r)
    out("p5.unavailable_retries", count=unavailable_retries)

    def pct(xs, q):
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)
    for name, xs in (("compare_and_put", cap_ms), ("load", load_ms)):
        out("p5.latency", verb=name, n=n,
            p50=pct(xs, 0.50), p95=pct(xs, 0.95), p99=pct(xs, 0.99),
            mean=round(statistics.mean(xs), 2), max=round(max(xs), 2))


def cmd_p6():
    c = new_client()
    pa = NoKVShadowProvider(c, WORKBENCH, "goal-alpha")
    pb = NoKVShadowProvider(c, WORKBENCH, "goal-beta")
    seq = []
    for i in range(3):
        for tag, p in (("alpha", pa), ("beta", pb)):
            rev = p.stat_revision()
            cid = str(uuid.uuid4())
            env = sample_envelope(command_id=cid, goal_id="goal-" + tag,
                                  expected_revision=rev, todo_id=f"t-{tag}-{i}")
            r = p.compare_and_put(rev, cid, env)
            seq.append((tag, rev, r["result"], r.get("authority_revision")))
    # alpha only advanced by alpha writes
    extra = NoKVShadowProvider(c, WORKBENCH, "goal-alpha")
    rev_alpha = extra.stat_revision()
    rev_beta = NoKVShadowProvider(c, WORKBENCH, "goal-beta").stat_revision()
    out("p6", sequence=seq, final_alpha_revision=rev_alpha,
        final_beta_revision=rev_beta,
        independent=(rev_alpha == 3 and rev_beta == 3))


if __name__ == "__main__":
    {"setup": cmd_setup, "p1": cmd_p1, "p2": cmd_p2, "p3": cmd_p3, "p3b": cmd_p3b,
     "p4pre": cmd_p4pre, "p4post": cmd_p4post, "p5": cmd_p5,
     "p6": cmd_p6}[sys.argv[1]]()
