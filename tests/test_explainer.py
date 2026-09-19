from datetime import date
from app.explainer import explain_engineer, explain_initiative, explain_task
from app.schemas import Dataset, Engineer, History, PlanRequest, Task


def task(tid, role="dev", initiative="I-1"):
    return Task(id=tid, initiative=initiative, title=f"Задача {tid}", team="Team-L", status="ToDo",
                priority=10, sp=3, estimated_hours=20, roles={role: 20})


def data(tasks, engineers=None, dependencies=None):
    return Dataset(tasks=tasks, engineers=engineers or [], dependencies=dependencies or [],
                   history=[History(date=date(2026, 1, 1), team="Team-L", achieved=10, planned=10)])


def row(tid, code, status="deferred", start=None, finish=None, reason=None):
    return dict(task_id=tid, initiative="I-1", title=f"Задача {tid}", team="Team-L", status=status, code=code,
                reason=reason or code, priority=10, remaining_sp=3, remaining_hours=20,
                start=start, finish=finish, chunks=[])


def plan(rows, initiatives=None, allocations=None):
    return dict(tasks=rows, initiatives=initiatives or [], allocations=allocations or [])


def test_explain_task_missing_role():
    source = data([task("A", "qa"), task("B")], dependencies=[("A", "B")])
    result = explain_task("A", plan([row("A", "missing_role")]), source, PlanRequest())
    assert result["explanation"] and len(result["suggested_actions"]) == 3
    assert result["affected_tasks"] == ["B"]


def test_explain_task_horizon():
    result = explain_task("A", plan([row("A", "horizon", reason="Не вошло; ограничение: SP: лимит 8. Осталось 20%")]),
                          data([task("A")]), PlanRequest())
    assert "горизонт" in result["explanation"] or "12-недельн" in result["explanation"]
    assert result["suggested_actions"]


def test_explain_task_dependency():
    source = data([task("A"), task("B")], dependencies=[("A", "B")])
    result = explain_task("B", plan([row("A", "horizon"), row("B", "dependency")]), source, PlanRequest())
    assert "A" in result["explanation"] and result["suggested_actions"]


def test_explain_task_planned():
    result = explain_task("A", plan([row("A", "scheduled", "planned", 1, 2)]), data([task("A")]), PlanRequest())
    assert "включена в план" in result["explanation"] and result["start"] == 1 and result["finish"] == 2


def test_explain_initiative_feasible():
    source = data([task("A")])
    result = explain_initiative("I-1", plan([row("A", "scheduled", "planned")],
                                              [dict(id="I-1", feasible=True, done=False, planned_tasks=1, blocked_tasks=[])]),
                                source, PlanRequest())
    assert result["feasible"] and result["explanation"] and result["suggested_actions"]


def test_explain_initiative_blocked():
    source = data([task("A")])
    result = explain_initiative("I-1", plan([row("A", "horizon")],
                                              [dict(id="I-1", feasible=False, done=False, planned_tasks=0, blocked_tasks=["A"])]),
                                source, PlanRequest())
    assert not result["feasible"] and result["blocked_reasons"] and result["suggested_actions"]


def test_explain_engineer_with_load():
    engineer = Engineer(id="ENG-1", team="Team-L", role="dev", grade="Senior", skills=["python"], rate=1)
    result = explain_engineer("ENG-1", plan([], allocations=[dict(engineer_id="ENG-1", sprint=1, hours=20, task_id="A")]),
                              data([task("A")], [engineer]), PlanRequest())
    assert len(result["sprint_loads"]) == 6 and "ENG-1" in result["explanation"]


def test_explain_task_alternatives_not_empty():
    result = explain_task("A", plan([row("A", "missing_role")]), data([task("A", "qa")]), PlanRequest())
    assert len(result["suggested_actions"]) >= 2


def test_explain_unknown_task_returns_none():
    assert explain_task("NONEXISTENT", plan([]), data([task("A")]), PlanRequest()) is None
