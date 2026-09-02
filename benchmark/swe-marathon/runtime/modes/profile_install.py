"""安装一份隔离的 LoopX profile，供三种模式共用。

上游 benchmark/deepswe/README.md 要求 treatment 臂有三项独立的产品路径证据：

  1. 该 profile 渲染出的 Goal body；
  2. LoopX 技能装进 app-server 实际使用的那个 CODEX_HOME；
  3. body 里点名的那个 release-snapshot CLI 确实存在。

只做第 1 项是不够的——实测过：body 里写着让模型用 `loopx-project` /
`loopx-self-repair` 技能、跑 `loopx ...` 命令，但技能没装、PATH 上的 `loopx` 还是
另一个安装，于是模型拿到一份自己无法执行的指令，跑满预算、工作区零改动、
且不报错。三项必须一起给。

`install_native_codex_profile` 一次把三项都办了，返回的 NativeCodexProfile 里
codex_home / cli_bin / required_skill_ids 就是那三项证据。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopx.capabilities.benchmark_toolkit.native_codex_profile import (
    NativeCodexProfile,
    NativeCodexProfileError,
    install_native_codex_profile,
    native_codex_profile_environment,
)


class ProfileError(RuntimeError):
    """隔离 profile 没装成。"""


@dataclass(frozen=True)
class InstalledProfile:
    """装好的 profile + 它的公开身份摘要。"""

    profile: NativeCodexProfile

    @property
    def cli_bin(self) -> str:
        return str(self.profile.cli_bin)

    @property
    def codex_home(self) -> str:
        return str(self.profile.codex_home)

    @property
    def required_skill_ids(self) -> tuple[str, ...]:
        return tuple(self.profile.required_skill_ids)

    def env(self, *, base: dict[str, str] | None = None) -> dict[str, str]:
        """app-server 该用的环境。

        native_codex_profile_environment 会把 HOME/CODEX_HOME/PATH 指到 profile
        里，并且是 credential-free 的：模型凭证只通过 provider 网关的 URL 和一个
        固定的非密 env 哨兵进去，不把宿主机的密钥暴露给 danger-full-access 的
        agent。
        """

        return dict(native_codex_profile_environment(
            self.profile, base_env=base if base is not None else dict(os.environ)
        ))

    def receipt(self) -> dict[str, Any]:
        """写进产物的公开身份，只有摘要和 id，不含本地路径。"""

        p = self.profile
        return {
            "source_revision": p.source_revision,
            "source_clean": p.source_clean,
            "skills_digest": p.skills_digest,
            "required_skill_ids": list(p.required_skill_ids),
            "materialized_skill_ids": list(p.materialized_skill_ids),
        }


def install(source_root: str | Path, profile_root: str | Path, *,
            python_executable: str | None = None,
            require_clean_source: bool = False) -> InstalledProfile:
    """装一份 profile。

    profile_root 必须不存在或为空——上游刻意不修复半装的 profile，因为混着两个
    安装版本会让整个 treatment 失效。所以每次跑用一个新目录。

    require_clean_source 默认放宽：wen 里的 loopx 是带本地改动的工作副本时，
    严格模式会直接拒装。跑正式对照时应当传 True。
    """

    try:
        profile = install_native_codex_profile(
            source_root,
            profile_root,
            python_executable=python_executable,
            require_clean_source=require_clean_source,
        )
    except NativeCodexProfileError as exc:
        raise ProfileError(f"profile 安装失败: {exc}") from exc
    return InstalledProfile(profile=profile)
