"""Stable, product-neutral extension contracts for Agent Core."""

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeAlias, cast


SideEffectClassification = Literal["none", "reversible", "irreversible"]
RiskClassification = Literal["low", "medium", "high"]
ToolExecutor: TypeAlias = Callable[[dict[str, object], str], Awaitable[object]]
SkillInstructionLoader: TypeAlias = Callable[[], str]

_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_JSON_TYPES: dict[str, type[object] | tuple[type[object], ...]] = {
    "array": list,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "object": dict,
    "string": str,
}


class ToolArgumentsError(ValueError):
    """Raised when arguments do not satisfy a Tool's input schema."""


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


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    call_id: str
    name: str
    ok: bool
    result: object | None = None
    error: str | None = None
    detail: str | None = None


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
    python_type = _JSON_TYPES.get(expected) if isinstance(expected, str) else None
    if python_type is not None:
        if expected in {"integer", "number"} and isinstance(value, bool):
            raise ToolArgumentsError(f"{path} must be {expected}")
        if not isinstance(value, python_type):
            raise ToolArgumentsError(f"{path} must be {expected}")
    raw_enum = schema.get("enum")
    if isinstance(raw_enum, (list, tuple)) and value not in raw_enum:
        raise ToolArgumentsError(f"{path} must be one of {list(raw_enum)}")
    if isinstance(value, Mapping):
        _validate_object(path, schema, cast(Mapping[str, object], value))
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        items_schema = cast(Mapping[str, object], schema["items"])
        for index, item in enumerate(value):
            _validate_value(f"{path}[{index}]", items_schema, item)


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
    "ToolExecutionResult",
    "ToolExecutor",
    "ToolMetadata",
    "validate_tool_arguments",
]
