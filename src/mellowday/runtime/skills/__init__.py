"""MellowDay skills package: discovery, metadata, token retrieval, evolution and evaluation.

The package keeps the original token (lexical) retrieval route: no vector store and no
extra third-party dependency is required. All persistent state lives under
:func:`mellowday.paths.skills_dir`, :func:`mellowday.paths.skills_archive_dir` and
:func:`mellowday.paths.evolution_dir`.

The names listed in :data:`__all__` are the stable public surface described by
docs/specs/CONTRACTS.md section 4.5 and are importable directly from
``mellowday.runtime.skills```.
"""
from __future__ import annotations

from .frontmatter import FrontmatterResult, format_frontmatter, parse_frontmatter
from .online_skill_evolution import (
    ConfirmWrite,
    OnlineSkillCandidate,
    SideQuery,
    extract_online_skill_candidate,
    judge_retrieved_skill_usage,
    maintain_online_skill_candidate,
    online_ingest,
)
from .online_skill_eval import (
    ONLINE_EVAL_DIR,
    evaluate_online_skill_evolution,
    evaluate_online_skill_evolution_async,
    format_online_skill_eval,
    format_online_skill_eval_async,
)
from .skill_evolution import (
    HISTORY_DIR,
    ONLINE_PROVENANCE_INDEX,
    ONLINE_PROVENANCE_LOG,
    SKILL_USAGE_STATS,
    USAGE_LOG,
    create_skill_file,
    evolve_skill_file,
    format_skill_stats,
    get_evolution_dir,
    load_skill_stats,
    record_online_skill_provenance,
    record_skill_feedback,
    record_skill_invocation,
    record_skill_usage_judgments,
    resolve_skill_file,
)
from .instruction_merge import (
    merge_instructions,
    rule_overlap,
    rule_similarity,
    split_evolution_notes,
    split_rule_units,
)
from .request_scope import (
    classify_request_scope,
    one_off_skip_reason,
    user_turn_texts,
)
from .skill_management import (
    SkillManagementError,
    UnknownSkillError,
    disable_skill,
    enable_skill,
    get_skill_detail,
    get_skill_version_content,
    list_skill_versions,
    list_skills,
    restore_skill_version,
    update_skill,
)
from .skills import (
    RETRIEVAL_MIN_CONTENT_TERMS,
    RETRIEVAL_MIN_SCORE,
    SkillDefinition,
    build_skill_descriptions,
    create_skill,
    discover_skills,
    evolve_skill,
    execute_skill,
    format_retrieved_skill_context,
    get_skill_by_name,
    is_relevant_hit,
    record_feedback,
    record_online_provenance,
    record_usage_judgments,
    reset_skill_cache,
    resolve_skill_prompt,
    retrieve_relevant_skills,
    skill_stats,
)

__all__ = [
    # 契约 4.5：发现、元信息、检索、加载
    "SkillDefinition",
    "discover_skills",
    "get_skill_by_name",
    "execute_skill",
    "resolve_skill_prompt",
    "build_skill_descriptions",
    "retrieve_relevant_skills",
    "format_retrieved_skill_context",
    # 检索相关性判据（t19）：分数下限 + 多字词项下限
    "RETRIEVAL_MIN_SCORE",
    "RETRIEVAL_MIN_CONTENT_TERMS",
    "is_relevant_hit",
    "reset_skill_cache",
    "create_skill",
    "evolve_skill",
    "record_feedback",
    "skill_stats",
    "record_usage_judgments",
    # 技能管理（I24）：查看、启停、版本历史与版本回退
    "list_skills",
    "disable_skill",
    "enable_skill",
    "list_skill_versions",
    "restore_skill_version",
    "get_skill_detail",
    "update_skill",
    "get_skill_version_content",
    "SkillManagementError",
    "UnknownSkillError",
    # 一次性要求判定（I11/t12）：自动学习的写入门槛
    "classify_request_scope",
    "one_off_skip_reason",
    "user_turn_texts",
    # 规则级合并（C 缺陷修复）：合并/编辑正文时的规则保全
    "merge_instructions",
    "split_rule_units",
    "split_evolution_notes",
    "rule_similarity",
    "rule_overlap",
    # 契约 4.5：演化与评测
    "create_skill_file",
    "evolve_skill_file",
    "resolve_skill_file",
    "load_skill_stats",
    "format_skill_stats",
    "record_skill_invocation",
    "record_skill_feedback",
    "record_online_provenance",
    "extract_online_skill_candidate",
    "maintain_online_skill_candidate",
    "online_ingest",
    "judge_retrieved_skill_usage",
    # 供网页层适配调用的辅助符号
    "FrontmatterResult",
    "OnlineSkillCandidate",
    "SideQuery",
    "ConfirmWrite",
    "format_frontmatter",
    "parse_frontmatter",
    "get_evolution_dir",
    "record_online_skill_provenance",
    "record_skill_usage_judgments",
    "evaluate_online_skill_evolution",
    "evaluate_online_skill_evolution_async",
    "format_online_skill_eval",
    "format_online_skill_eval_async",
    "ONLINE_EVAL_DIR",
    "USAGE_LOG",
    "ONLINE_PROVENANCE_LOG",
    "ONLINE_PROVENANCE_INDEX",
    "SKILL_USAGE_STATS",
    "HISTORY_DIR",
]
