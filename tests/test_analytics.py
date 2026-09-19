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
