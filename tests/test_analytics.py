from datetime import date
from app.analytics import star_map
from app.planner import build_plan
from app.schemas import Dataset, Engineer, History, PlanRequest, Task


def task(tid, role):
    return Task(id=tid, initiative="I-1", title=tid, team="Team-L", status="ToDo", priority=1,
                sp=1, estimated_hours=1, roles={role: 1})


def stars(tasks, engineers):
    source = Dataset(tasks=tasks, engineers=engineers, dependencies=[],
                     history=[History(date=date(2026, 1, 1), team="Team-L", achieved=10, planned=10)])
    return star_map(source, PlanRequest(), build_plan(source, PlanRequest()))


def skill(result, name):
    return next(item for item in result["critical_skills"] if item["skill"] == name)


def test_bus_factor_bf0_role_is_critical():
    item = skill(stars([task("A", "разработчик 1с")], []), "разработчик 1с")
    assert item["bus_factor"] == 0
    assert item["risk_level"] == "critical"
    assert item["risk_category"] == "role_deficit"


def test_bus_factor_unique_skill_with_3_tasks_is_critical():
    engineer = Engineer(id="ENG-1", team="Team-L", role="разработчик java", grade="Senior",
                        skills=["spring"], rate=1)
    item = skill(stars([task("A", "разработчик java"), task("B", "разработчик java"),
                        task("C", "разработчик java")], [engineer]), "spring")
    assert item["risk_level"] == "critical"
    assert item["risk_category"] == "unique_skill"


def test_bus_factor_bf1_with_1_task_is_high():
    engineer = Engineer(id="ENG-1", team="Team-L", role="разработчик java", grade="Senior",
                        skills=["spring"], rate=1)
    item = skill(stars([task("A", "разработчик java")], [engineer]), "spring")
    assert item["risk_level"] == "high"
    assert item["risk_category"] == "potential"


def test_bus_factor_parttime_is_critical():
    engineer = Engineer(id="ENG-1", team="Team-L", role="разработчик java", grade="Senior",
                        skills=["spring"], rate=.4)
    item = skill(stars([task("A", "разработчик java")], [engineer]), "spring")
    assert item["risk_level"] == "critical"
    assert item["risk_category"] == "parttime"


def test_bus_factor_no_affected_is_medium():
    engineer = Engineer(id="ENG-1", team="Team-L", role="разработчик java", grade="Senior",
                        skills=["spring"], rate=1)
    item = skill(stars([task("A", "тестировщик")], [engineer]), "spring")
    assert item["risk_level"] == "medium"
    assert item["risk_category"] == "potential"


from app.analytics import group_risks, risks


def risk_data(tasks, engineers=None, dependencies=None):
    return Dataset(tasks=tasks, engineers=engineers or [], dependencies=dependencies or [],
                   history=[History(date=date(2026, 1, 1), team="Team-L", achieved=10, planned=10)])


def risk_row(tid, status="deferred", code="horizon", finish=None):
    return dict(task_id=tid, initiative="I-1", status=status, code=code, reason=code, finish=finish)


def risk_plan(rows, initiatives=None):
    return dict(tasks=rows, initiatives=initiatives or [])


def test_risks_horizon_is_red():
    items = risks(risk_plan([risk_row("A")]), None, risk_data([task("A", "dev")]))
    item = next(item for item in items if item["kind"] == "horizon")
    assert item["level"] == "red" and item["affected_tasks"] == ["A"]


def test_risks_dependency_is_red():
    items = risks(risk_plan([risk_row("A", code="dependency")]), None, risk_data([task("A", "dev")]))
    assert next(item for item in items if item["kind"] == "dependency")["level"] == "red"


def test_risks_role_shortage_is_orange():
    items = risks(risk_plan([risk_row("A", code="missing_role")]), None, risk_data([task("A", "qa")]))
    item = next(item for item in items if item["kind"] == "role_shortage")
    assert item["level"] == "orange" and item["affected_tasks"] == ["A"]


def test_risks_cancelled_initiative_is_red():
    items = risks(risk_plan([], [dict(id="I-1", feasible=False, blocked_tasks=["A"])]), None,
                  risk_data([task("A", "dev")]))
    item = next(item for item in items if item["kind"] == "cancelled_initiative")
    assert item["level"] == "red" and item["affected_initiatives"] == ["I-1"]


def test_risks_cascade_needs_baseline():
    items = risks(risk_plan([risk_row("A", status="planned", finish=2)]), None, risk_data([task("A", "dev")]))
    assert not any(item["kind"] == "cascade" for item in items)
    assert any(item["kind"] == "info" for item in items)


def test_risks_cascade_after_baseline():
    source = risk_data([task("A", "dev"), task("B", "dev")], dependencies=[("A", "B")])
    baseline = risk_plan([risk_row("A", status="planned", finish=1)])
    items = risks(risk_plan([risk_row("A", status="planned", finish=2)]), baseline, source)
    item = next(item for item in items if item["kind"] == "cascade")
    assert item["level"] == "yellow" and item["affected_tasks"] == ["B"]


def test_risks_grouping_summary():
    result = group_risks([dict(level="red"), dict(level="yellow"), dict(level="orange"), dict(level="gray")])
    assert result["summary"] == dict(critical=1, cascade=1, resource=1, info=1)
