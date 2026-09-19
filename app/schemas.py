"""Небольшие структуры данных, общие для загрузчика, API и алгоритма."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Task(Model):
    id: str
    initiative: str
    title: str
    team: str
    status: Literal["ToDo", "InProgress", "Done"]
    priority: float
    sp: float = Field(ge=0)
    estimated_hours: float = Field(ge=0)
    roles: dict[str, float]
    spent: dict[str, float] = Field(default_factory=dict)
    created: date | None = None
    actual_end: date | None = None


class Engineer(Model):
    id: str
    team: str
    role: str
    grade: str
    skills: list[str]
    rate: float = Field(gt=0, le=1)


class History(Model):
    date: date
    team: str
    achieved: float = Field(ge=0)
    planned: float = Field(ge=0)


class Dataset(Model):
    tasks: list[Task]
    engineers: list[Engineer]
    history: list[History]
    dependencies: list[tuple[str, str]]
    issues: list[dict] = Field(default_factory=list)


class TaskOverride(Model):
    remaining_hours: dict[str, float] | None = None
    remaining_sp: float | None = Field(default=None, ge=0)
    # Наличие ключа роли с [] означает явно подтверждённое отсутствие доп. требований.
    required_skills: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_hours(self):
        if self.remaining_hours is not None:
            validate_hours(self.remaining_hours)
        return self


def validate_hours(hours):
    import math
    if any(not math.isfinite(v) or v < 0 for v in hours.values()):
        raise ValueError("Часы должны быть конечными неотрицательными числами")


class PlanRequest(Model):
    start_date: date = date(2026, 6, 15)
    strict_skills: bool = False
    overrides: dict[str, TaskOverride] = Field(default_factory=dict)
    # engineer_id -> sprint number -> available fraction, applies across teams.
    availability: dict[str, dict[int, float]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_availability(self):
        import math
        for values in self.availability.values():
            if any(s < 1 or s > 6 or not math.isfinite(v) or not 0 <= v <= 1
                   for s, v in values.items()):
                raise ValueError("Доступность: спринт 1–6, доля от 0 до 1")
        return self


class CriticalSkill(Model):
    scope: str
    skill: str
    bus_factor: int = Field(ge=0)
    holder: str | None = None
    holder_name: str | None = None
    holder_role: str | None = None
    holder_team: str | None = None
    holder_rate: float | None = None
    affected_tasks: list[str] = Field(default_factory=list)
    affected_initiatives: list[str] = Field(default_factory=list)
    risk_level: Literal["critical", "high", "medium"]
    risk_category: Literal["role_deficit", "unique_skill", "parttime", "potential"]
    explanation: str


class BusFactorReport(Model):
    total_skills: int
    critical_count: int
    high_count: int
    medium_count: int
    critical_skills: list[CriticalSkill]
    healthy_skills: list[dict]


class TaskFact(Model):
    task_id: str
    status: Literal["InProgress", "Done"]
    remaining_hours: dict[str, float] = Field(default_factory=dict)
    remaining_sp: float = Field(default=0, ge=0)
    spent_hours: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_fact(self):
        validate_hours(self.remaining_hours)
        validate_hours(self.spent_hours)
        if self.status == "InProgress" and (not any(self.remaining_hours.values()) or self.remaining_sp <= 0):
            raise ValueError("Для незавершённой задачи нужны положительные остатки часов и SP")
        if self.status == "Done" and (any(self.remaining_hours.values()) or self.remaining_sp):
            raise ValueError("У Done остатки должны быть нулевыми")
        return self


class SprintFact(Model):
    sprint: int = Field(ge=1, le=6)
    tasks: list[TaskFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_tasks(self):
        if len({t.task_id for t in self.tasks}) != len(self.tasks):
            raise ValueError("Задача повторяется в факте спринта")
        return self
