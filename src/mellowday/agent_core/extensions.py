"""Stable, product-neutral extension contracts for Agent Core."""

from __future__ import annotations

import re
from copy import deepcopy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeAlias, cast


SideEffectClassification = Literal["none", "reversible", "irreversible"]
RiskClassification = Literal["low", "medium", "high"]
ToolExecutor: TypeAlias = Callable[[dict[str, object], str], Awaitable[object]]
SkillInstructionLoader: TypeAlias = Callable[[], str]

_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_SIDE_EFFECT_CLASSIFICATIONS = frozenset(("none", "reversible", "irreversible"))
_RISK_CLASSIFICATIONS = frozenset(("low", "medium", "high"))
_JSON_TYPES: dict[str, type[object] | tuple[type[object], ...]] = {
    "array": list,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
    "object": dict,
    "string": str,
}


class ToolArgumentsError(ValueError):
    """Raised when arguments do not satisfy a Tool's input schema."""


class ToolClarificationRequired(ValueError):
    """Raised when a Tool needs more User input before it can execute."""


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    name: str
    description: str
    input_schema: dict[str, object]
    permission_requirements: tuple[str, ...]
    side_effect: SideEffectClassification
    risk: RiskClassification


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    input_schema: Mapping[str, object]
    executor: ToolExecutor = field(repr=False, compare=False)
    permission_requirements: tuple[str, ...] = ()
    side_effect: SideEffectClassification = "none"
    risk: RiskClassification = "low"

    def __post_init__(self) -> None:
        if _TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError(f"invalid Tool name: {self.name!r}")
        if not self.description.strip():
            raise ValueError("Tool description must not be empty")
        if not callable(self.executor):
            raise TypeError("Tool executor must be callable")
        if self.side_effect not in _SIDE_EFFECT_CLASSIFICATIONS:
            raise ValueError(
                f"invalid side-effect classification: {self.side_effect!r}"
            )
        if self.risk not in _RISK_CLASSIFICATIONS:
            raise ValueError(f"invalid risk classification: {self.risk!r}")
        schema = dict(self.input_schema)
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        if schema["type"] != "object":
            raise ValueError("Tool input schema must describe an object")
        object.__setattr__(self, "input_schema", schema)
        object.__setattr__(
            self,
            "permission_requirements",
            tuple(str(item) for item in self.permission_requirements),
        )

    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema),
            permission_requirements=self.permission_requirements,
            side_effect=self.side_effect,
            risk=self.risk,
        )


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, object] | None
    intent_clarity: Literal["clear", "ambiguous"] = "clear"


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    call_id: str
    name: str
    ok: bool
    result: object | None = None
    error: str | None = None
    detail: str | None = None
    undo: UndoMetadata | None = None


@dataclass(frozen=True, slots=True)
class UndoMetadata:
    tool: str
    arguments: dict[str, object]

    def __post_init__(self) -> None:
        if _TOOL_NAME.fullmatch(self.tool) is None:
            raise ValueError(f"invalid undo Tool name: {self.tool!r}")
        object.__setattr__(self, "arguments", deepcopy(self.arguments))


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    value: object
    undo: UndoMetadata | None = None


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str
    description: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    instruction_loader: SkillInstructionLoader = field(repr=False, compare=False)
    enabled_by_default: bool = True

    def __post_init__(self) -> None:
        if _TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError(f"invalid Skill name: {self.name!r}")
        if not self.description.strip():
            raise ValueError("Skill description must not be empty")
        if not callable(self.instruction_loader):
            raise TypeError("Skill instruction loader must be callable")

    def metadata(self, *, enabled: bool) -> SkillMetadata:
        return SkillMetadata(
            name=self.name,
            description=self.description,
            enabled=enabled,
        )


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    name: str
    instructions: str


def validate_tool_arguments(
    schema: Mapping[str, object], arguments: Mapping[str, object] | None
) -> dict[str, object]:
    if not isinstance(arguments, Mapping):
        raise ToolArgumentsError("arguments must be an object")
    normalized = dict(arguments)
    _validate_object("arguments", schema, normalized)
    return normalized


def _validate_object(
    path: str, schema: Mapping[str, object], value: Mapping[str, object]
) -> None:
    raw_properties = schema.get("properties", {})
    properties = (
        cast(Mapping[str, object], raw_properties)
        if isinstance(raw_properties, Mapping)
        else {}
    )
    raw_required = schema.get("required", ())
    required = raw_required if isinstance(raw_required, (list, tuple)) else ()
    for key in required:
        if isinstance(key, str) and key not in value:
            raise ToolArgumentsError(f"{path}.{key} is required")
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(value) - set(properties))
        if unknown:
            raise ToolArgumentsError(f"{path} has unknown properties: {unknown}")
    for key, item in value.items():
        item_schema = properties.get(key)
        if isinstance(item_schema, Mapping):
            _validate_value(f"{path}.{key}", item_schema, item)


def _validate_value(path: str, schema: Mapping[str, object], value: object) -> None:
    expected = schema.get("type")
    if isinstance(expected, str) and not _matches_json_type(expected, value):
        raise ToolArgumentsError(f"{path} must be {expected}")
    if isinstance(expected, (list, tuple)):
        expected_types = [item for item in expected if isinstance(item, str)]
        if not expected_types or not any(
            _matches_json_type(item, value) for item in expected_types
        ):
            raise ToolArgumentsError(f"{path} must be one of {expected_types}")
    raw_enum = schema.get("enum")
    if isinstance(raw_enum, (list, tuple)) and value not in raw_enum:
        raise ToolArgumentsError(f"{path} must be one of {list(raw_enum)}")
    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        maximum_length = schema.get("maxLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            raise ToolArgumentsError(
                f"{path} is shorter than minLength {minimum_length}"
            )
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            raise ToolArgumentsError(
                f"{path} is longer than maxLength {maximum_length}"
            )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if (
            isinstance(minimum, (int, float))
            and not isinstance(minimum, bool)
            and value < minimum
        ):
            raise ToolArgumentsError(f"{path} is below minimum {minimum}")
        if (
            isinstance(maximum, (int, float))
            and not isinstance(maximum, bool)
            and value > maximum
        ):
            raise ToolArgumentsError(f"{path} is above maximum {maximum}")
    if isinstance(value, Mapping):
        _validate_object(path, schema, cast(Mapping[str, object], value))
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        items_schema = cast(Mapping[str, object], schema["items"])
        for index, item in enumerate(value):
            _validate_value(f"{path}[{index}]", items_schema, item)


def _matches_json_type(expected: str, value: object) -> bool:
    python_type = _JSON_TYPES.get(expected)
    if python_type is None:
        return True
    if expected in {"integer", "number"} and isinstance(value, bool):
        return False
    return isinstance(value, python_type)


__all__ = [
    "LoadedSkill",
    "RiskClassification",
    "SideEffectClassification",
    "Skill",
    "SkillInstructionLoader",
    "SkillMetadata",
    "Tool",
    "ToolArgumentsError",
    "ToolCall",
    "ToolClarificationRequired",
    "ToolExecutionResult",
    "ToolExecutor",
    "ToolMetadata",
    "ToolOutcome",
    "UndoMetadata",
    "validate_tool_arguments",
]
