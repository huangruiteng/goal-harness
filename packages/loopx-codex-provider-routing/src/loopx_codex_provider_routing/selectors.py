"""Credential-free selector definitions shared by CPA and the App catalog."""

from .contract import compile_catalog

SLOTS = ("a", "b", "c")
MODEL_FAMILIES = {"gpt-5.6-sol": "Sol", "gpt-6-astra": "Astra"}
ROUTES = {}
for model, label in MODEL_FAMILIES.items():
    for preferred in (None, *SLOTS):
        order = (
            list(SLOTS)
            if preferred is None
            else list(SLOTS[SLOTS.index(preferred) :] + SLOTS[: SLOTS.index(preferred)])
        )
        prefix = "auto" if preferred is None else f"codex-{preferred}"
        title = "Auto" if preferred is None else f"Prefer {preferred.upper()}"
        chain = " → ".join(s.upper() for s in order)
        for fast in (False, True):
            slug = ("fast/" if fast else "") + f"{prefix}/{model}"
            ROUTES[slug] = {
                "model": model,
                "order": order,
                "fast": fast,
                "tail": [],
                "display_name": f"{label} · {title} · "
                + ("Fast · " if fast else "")
                + f"Codex {chain}",
            }
# The second Auto is an explicit opt-in to a heterogeneous Standard fallback.
for model, label in MODEL_FAMILIES.items():
    ROUTES[f"auto-with-ds/{model}"] = {
        "model": model,
        "order": list(SLOTS),
        "fast": False,
        "tail": ["ark-text"],
        "display_name": f"{label} · Auto · A → B → C → DeepSeek",
    }
VISIBLE_SELECTORS = {
    f"{prefix}/{model}"
    for model in MODEL_FAMILIES
    for prefix in ("auto", "auto-with-ds")
}

ROUTES["gpt-5.6-luna"] = {
    "model": "gpt-5.6-luna",
    "order": list(SLOTS),
    "fast": False,
    "tail": [],
    "display_name": "Luna · Codex A → B → C",
}
FAST_MODELS = tuple(slug for slug, route in ROUTES.items() if route["fast"])


def aliases_for_slot(slot):
    if slot not in SLOTS:
        raise ValueError("unknown OAuth slot")
    entries = []
    for slug, route in ROUTES.items():
        entries.append(
            {
                "name": route["model"],
                "alias": slug,
                "display-name": route["display_name"],
                "force-mapping": True,
                "fork": slug.startswith("auto/"),
                "routing-priority": 400 - 100 * route["order"].index(slot),
            }
        )
    for model in MODEL_FAMILIES:
        entry = dict(next(e for e in entries if e["alias"] == f"auto/{model}"))
        entry["alias"] = model
        entries.append(entry)
    return entries


def routing_source():
    profiles = [
        {
            "id": f"codex-{s}",
            "provider": "codex",
            "priority": 400 - 100 * SLOTS.index(s),
            "input_modalities": ["text", "image"],
            "supports_fast": True,
            "tool_transports": ["function_call", "custom_tool_call"],
        }
        for s in SLOTS
    ]
    profiles.append(
        {
            "id": "ark-text",
            "provider": "openai_compatibility",
            "priority": 100,
            "input_modalities": ["text"],
            "supports_fast": False,
            "tool_transports": ["function_call", "custom_tool_call"],
        }
    )
    routes = []
    for slug, spec in ROUTES.items():
        if spec["fast"]:
            continue
        auto = slug.startswith(("auto/", "auto-with-ds/")) or slug == "gpt-5.6-luna"
        route = {
            "slug": slug,
            "display_name": spec["display_name"],
            "mode": "auto" if auto else "preferred",
            "ring": "codex-accounts",
            "entrypoint": "affinity_then_first"
            if auto
            else f"codex-{spec['order'][0]}",
            "fallback_tail": spec["tail"],
            "input_modalities": ["text", "image"],
            "supports_fast": not bool(spec["tail"]),
            "reasoning_levels": ["low", "medium", "high", "xhigh", "max"],
        }
        fast = ROUTES.get(f"fast/{slug}")
        if fast:
            route["fast_selector"] = {
                "display_name": fast["display_name"],
                "fallback_policy": "fast_capable_only",
            }
        routes.append(route)
    return {
        "profiles": profiles,
        "rings": [
            {
                "id": "codex-accounts",
                "members": [f"codex-{s}" for s in SLOTS],
                "max_cycles": 1,
            }
        ],
        "routes": routes,
    }


def compiled_routes():
    return compile_catalog(routing_source())


# The existing contract compiler owns ring traversal and Fast admission.
# Both credential aliases and App rows consume its resolved candidates.
for _row in compiled_routes()["selector_rows"]:
    _spec = ROUTES[_row["slug"]]
    _spec["order"] = [
        profile.removeprefix("codex-")
        for profile in _row["candidates"]
        if profile.startswith("codex-")
    ]
    _spec["tail"] = [
        profile for profile in _row["candidates"] if not profile.startswith("codex-")
    ]
