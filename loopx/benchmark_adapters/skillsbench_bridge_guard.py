from __future__ import annotations


LOOPX_COMMAND_INSTRUMENTATION_SOURCE = r'''
def loopx_subcommands(command: str) -> list[str]:
    try:
        tokens = shlex.split(command or "")
    except ValueError:
        tokens = (command or "").split()
    index = next(
        (
            offset
            for offset, token in enumerate(tokens)
            if token == "loopx" or token.endswith("/loopx")
        ),
        -1,
    )
    if index < 0:
        return []
    out: list[str] = []
    skip = False
    valued_options = {
        "--goal-id", "--todo-id", "--claimed-by", "--status", "--note",
        "--evidence", "--classification", "--registry", "--runtime-root",
        "--slots", "--source", "--format", "--project", "--goal-text",
        "--agent-id", "--host-surface", "--role", "--task-class",
        "--action-kind", "--text",
    }
    for token in tokens[index + 1:]:
        if skip:
            skip = False
            continue
        if token.startswith("--"):
            if "=" not in token and token in valued_options:
                skip = True
            continue
        if token.startswith("-"):
            continue
        if re.match(r"^[A-Za-z][A-Za-z0-9_-]{0,40}$", token):
            out.append(token)
            if len(out) >= 2:
                break
    return out

def loopx_invocation_count(command: str) -> int:
    try:
        lexer = shlex.shlex(
            command or "",
            posix=True,
            punctuation_chars=";&|" + chr(10),
        )
        lexer.whitespace = " " + chr(9) + chr(13)
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        tokens = (command or "").replace(chr(10), " ; ").split()
    segments = []
    current = []
    for token in tokens:
        if token and all(char in ";&|" or char == chr(10) for char in token):
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)

    count = 0
    assignment_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
    for segment in segments:
        index = 0
        while index < len(segment) and assignment_re.match(segment[index]):
            index += 1
        if index < len(segment) and segment[index] == "env":
            index += 1
            while index < len(segment) and (
                segment[index].startswith("-")
                or assignment_re.match(segment[index])
            ):
                index += 1
        if index < len(segment) and segment[index].rsplit("/", 1)[-1] == "loopx":
            count += 1
    return count

def enforce_single_loopx_invocation(count, record, append_record) -> None:
    if count <= 1:
        return
    stderr_text = (
        "bridge request rejected: send exactly one LoopX CLI command per "
        "operation=exec request" + chr(10)
    )
    complete_record = dict(record)
    complete_record.update({
        "record_phase": "complete",
        "returncode": 2,
        "success": False,
        "stdout_bytes": 0,
        "stderr_bytes": len(stderr_text.encode("utf-8")),
        "failure_category": "multiple_loopx_commands_per_bridge_request",
    })
    append_record(complete_record)
    sys.stderr.write(stderr_text)
    raise SystemExit(2)
'''.strip()
