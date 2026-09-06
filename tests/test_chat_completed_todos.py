import json
import threading
from urllib.request import urlopen
from urllib.request import Request
from urllib.error import HTTPError

import pytest

from loopx.chat_completed_todos import CompletedTodoPages
from loopx.chat_server import ChatHTTPServer, ChatRequestHandler
from loopx.control_plane.todos.contract import encode_metadata_value


def test_snapshot_pagination_is_bounded_and_stable():
    pages = CompletedTodoPages()
    rows = [{"todo_id": f"todo_{index}"} for index in range(4087)]
    calls = []
    def load():
        calls.append(True)
        return list(rows)
    result = pages.page(scope=("goal", "all"), cursor="", load=load)
    found = list(result["items"])
    rows.insert(0, {"todo_id": "todo_new"})
    while result["next_cursor"]:
        assert len(result["items"]) <= 40
        result = pages.page(scope=("goal", "all"), cursor=result["next_cursor"], load=load)
        found.extend(result["items"])
    assert len(found) == len({row["todo_id"] for row in found}) == 4087
    assert len(calls) == 1


def test_cursor_scope_expiry_and_capacity():
    pages = CompletedTodoPages()

    def load():
        return [{}] * 41

    cursor = pages.page(scope="a", cursor="", load=load)["next_cursor"]
    with pytest.raises(ValueError, match="expired"):
        pages.page(scope="b", cursor=cursor, load=load)
    for index in range(9):
        pages.page(scope=index, cursor="", load=load)
    assert len(pages._snapshots) == 8
    with pytest.raises(ValueError, match="expired"):
        pages.page(scope="a", cursor=cursor, load=load)
    cursor = pages.page(scope="a", cursor="", load=load)["next_cursor"]
    pages.ttl_seconds = 0
    with pytest.raises(ValueError, match="expired"):
        pages.page(scope="a", cursor=cursor, load=load)


def test_snapshot_byte_budget_is_enforced():
    pages = CompletedTodoPages()
    pages.max_cache_bytes = 10
    with pytest.raises(ValueError, match="too_large"):
        pages.page(scope="a", cursor="", load=lambda: [{"text": "x" * 100}])
    assert not pages._snapshots


@pytest.mark.parametrize("count", [85, 4087])
def test_http_history_reads_real_markdown_without_writes(tmp_path, count):
    state = tmp_path / "active.md"
    text = (f"Inspect {tmp_path}/results.txt " + "complete task description " * 25)[:420]
    evidence = f"Verified output at {tmp_path}/results.txt"
    state.write_text("# Synthetic Goal\n\n## Agent Todo\n" + "\n".join(
        f"- [x] {text}{index}\n  <!-- loopx:todo todo_id=todo_history_{index} status=done task_class=advancement_task note={encode_metadata_value(evidence)} -->" for index in range(count)
    ) + "\n\n## User Todo\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"runtime_root": str(tmp_path / "runtime"), "goals": [{"id": "history-goal", "repo": str(tmp_path), "state_file": "active.md"}]}))
    before = state.read_bytes()
    server = ChatHTTPServer(("127.0.0.1", 0), ChatRequestHandler)
    server.registry_path = registry
    server.runtime_root_override = None
    server.verbose = False
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/chat/completed-todos?goal_id=history-goal"
        with urlopen(url) as response:
            page = json.load(response)
        assert page["total"] == count
        assert len(page["items"]) == 40
        assert page["next_cursor"]
        assert page["items"][0]["text"].startswith(text)
        assert len(page["items"][0]["text"]) > 400
        assert page["items"][0]["evidence"] == evidence
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(url, headers={"Origin": "https://unrelated.example"}))
        assert denied.value.code == 403
        assert state.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
