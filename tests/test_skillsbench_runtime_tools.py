from loopx.benchmark_adapters import skillsbench_dockerfile_runtime
from scripts.skillsbench_automation_loop import (
    DOCKER_BENCHMARK_EGRESS_PROXY_BEGIN,
    DOCKER_CODEX_ACP_RUNTIME_TOOLS_BEGIN,
    _benchflow_environment_name,
    patch_dockerfile_codex_acp_runtime_tools,
    stage_task_for_sandbox,
)


def test_benchflow_environment_name_preserves_keyword_environment() -> None:
    assert _benchflow_environment_name((), {"environment": "docker"}) == "docker"
    assert _benchflow_environment_name(("docker",), {}) == "docker"


def test_runtime_tools_retries_apt_with_public_mirrors(tmp_path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM ubuntu:24.04\n", encoding="utf-8")

    assert patch_dockerfile_codex_acp_runtime_tools(dockerfile) is True

    staged_text = dockerfile.read_text(encoding="utf-8")
    assert DOCKER_CODEX_ACP_RUNTIME_TOOLS_BEGIN in staged_text
    assert "if ! apt-get update -qq; then" in staged_text
    assert (
        skillsbench_dockerfile_runtime.DEFAULT_UBUNTU_APT_MIRROR_BASE
        in staged_text
    )
    assert (
        skillsbench_dockerfile_runtime.DEFAULT_DEBIAN_APT_MIRROR_BASE
        in staged_text
    )
    assert (
        skillsbench_dockerfile_runtime.DEFAULT_DEBIAN_SECURITY_MIRROR_BASE
        in staged_text
    )
    assert staged_text.count("apt-get update -qq") == 2
    assert (
        staged_text.index("if ! apt-get update -qq; then")
        < staged_text.index("apt-get install -y -qq")
    )
    assert patch_dockerfile_codex_acp_runtime_tools(dockerfile) is False
    assert dockerfile.read_text(encoding="utf-8") == staged_text


def test_staging_places_proxy_before_runtime_network_steps(tmp_path) -> None:
    task_path = tmp_path / "task"
    environment_path = task_path / "environment"
    environment_path.mkdir(parents=True)
    (environment_path / "Dockerfile").write_text(
        "FROM ubuntu:24.04\n",
        encoding="utf-8",
    )

    staged_path, metadata = stage_task_for_sandbox(
        task_path=task_path,
        jobs_dir=tmp_path / "jobs",
        job_name="proxy-order",
        sandbox="docker",
        benchmark_egress_proxy_env={
            "HTTP_PROXY": "http://127.0.0.1:18080",
            "HTTPS_PROXY": "http://127.0.0.1:18080",
        },
    )

    staged_text = (staged_path / "environment" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert metadata["benchmark_egress_proxy_dockerfile_env_patch_applied"] is True
    assert metadata["codex_acp_runtime_tools_patch_applied"] is True
    assert (
        staged_text.index(DOCKER_BENCHMARK_EGRESS_PROXY_BEGIN)
        < staged_text.index(DOCKER_CODEX_ACP_RUNTIME_TOOLS_BEGIN)
    )
