from datetime import date
from app.diff import diff_plans, list_deferred
from app.schemas import Dataset, History, Task


def make_data():
    return Dataset(tasks=[Task(id="A", initiative="I-1", title="A", team="Team-L", status="ToDo", priority=1,
                               sp=2, estimated_hours=20, roles={"dev":20}),
                          Task(id="B", initiative="I-1", title="B", team="Team-L", status="ToDo", priority=1,
                               sp=2, estimated_hours=20, roles={"qa":20}),
                          Task(id="C", initiative="I-2", title="C", team="Team-X", status="ToDo", priority=1,
                               sp=2, estimated_hours=20, roles={"analyst":20})],
                   engineers=[], dependencies=[], history=[History(date=date(2026, 1, 1), team="Team-L", achieved=1, planned=1)])


def row(task_id, status="planned", code="scheduled", start=1, finish=2, initiative="I-1"):
    return dict(task_id=task_id, initiative=initiative, title=task_id, team="Team-L", status=status, code=code,
                reason=f"Причина {code}", priority=1, remaining_sp=2, remaining_hours=20,
                start=start, finish=finish, chunks=[])


def plan(tasks, feasible=True):
    return dict(tasks=tasks, initiatives=[dict(id="I-1", feasible=feasible, done=False, planned_tasks=1,
                                                blocked_tasks=[t["task_id"] for t in tasks if t["status"] != "planned"])])


def test_diff_shifts():
    result = diff_plans(plan([row("A", start=1, finish=2)]), plan([row("A", start=3, finish=4)]), make_data())
    assert result["shifts"][0]["task_id"] == "A"
    assert "С1 → С3" in result["shifts"][0]["reason"]


def test_diff_added():
    result = diff_plans(plan([row("A", "deferred", "horizon", None, None)]), plan([row("A")]), make_data())
    assert result["added"] == [{"task_id":"A", "initiative":"I-1", "reason":"Добавлена после пересчёта: Причина scheduled"}]


def test_diff_removed():
    result = diff_plans(plan([row("A")]), plan([row("A", "deferred", "horizon", None, None)]), make_data())
    assert result["removed"][0]["new_status"] == "deferred"


def test_diff_initiatives_affected():
    result = diff_plans(plan([row("A")], True), plan([row("A", "deferred", "horizon", None, None)], False), make_data())
    assert result["initiatives"] == [{"id":"I-1", "was_feasible":True, "now_feasible":False, "blocked_tasks":["A"]}]


def test_diff_summary_counts():
    old = plan([row("A", start=1, finish=2), row("B", "deferred", "horizon", None, None), row("C", initiative="I-1")], True)
    new = plan([row("A", start=2, finish=3), row("B"), row("C", "deferred", "dependency", None, None)], False)
    assert diff_plans(old, new, make_data())["summary"] == dict(shifts=1, added=1, removed=1, initiatives_affected=1)


def test_deferred_groups_by_code():
    tasks = [row("A", "deferred", "missing_role", None, None), row("B", "deferred", "missing_skills", None, None),
             row("C", "deferred", "horizon", None, None), row("D", "deferred", "dependency", None, None),
             row("E", "needs_input", "unknown_remaining", None, None)]
    result = list_deferred(plan(tasks), make_data())
    assert all(result[code] for code in ("missing_role", "missing_skills", "horizon", "dependency", "unknown_remaining"))
    assert result["summary"]["total"] == 5


def test_deferred_empty_when_all_planned():
    result = list_deferred(plan([row("A"), row("B")]), make_data())
    assert result["summary"]["total"] == 0
    assert not any(result[code] for code in (*("missing_role", "missing_skills", "horizon", "dependency", "unknown_skills", "unknown_remaining"), "other"))
