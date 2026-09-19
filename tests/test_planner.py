from collections import defaultdict
from datetime import date
import pytest
from app.schemas import Dataset, Task, Engineer, History, PlanRequest, TaskOverride, SprintFact
from app.planner import build_plan
from app.loader import validate_dataset
from app.main import validate_fact
from app.analytics import metrics, star_map


def task(tid="A", team="T", hours=80, sp=8, priority=10, initiative=None):
    return Task(id=tid,initiative=initiative or tid,title=tid,team=team,status="ToDo",priority=priority,
                sp=sp,estimated_hours=hours,roles={"dev":hours})


def engineer(eid="E", team="T", rate=1):
    return Engineer(id=eid,team=team,role="dev",grade="Middle",skills=["python"],rate=rate)


def dataset(tasks=None, engineers=None, dependencies=None, velocity=10):
    tasks = tasks or [task()]
    return Dataset(tasks=tasks,engineers=engineers or [engineer()],dependencies=dependencies or [],
                   history=[History(date=date(2026,1,1),team=t,achieved=velocity,planned=velocity)
                            for t in sorted({t.team for t in tasks})])


def rows(plan):
    return {t["task_id"]:t for t in plan["tasks"]}


def assert_limits(plan, data, settings):
    hours, team_hours = defaultdict(float), defaultdict(float)
    for a in plan["allocations"]:
        hours[(a["sprint"],a["engineer_id"])] += a["hours"]
        team_hours[(a["sprint"],a["engineer_id"],a["team"])] += a["hours"]
    for (s,e),h in hours.items():
        assert h <= 80*settings.availability.get(e,{}).get(s,1) + 1e-6
    for (s,e,t),h in team_hours.items():
        rate = next(x.rate for x in data.engineers if x.id==e and x.team==t)
        assert h <= 80*rate*settings.availability.get(e,{}).get(s,1) + 1e-6
    assert all(x["sp"] <= x["capacity"]+1e-6 for x in plan["loads"])


def test_large_task_split_and_dependency_next_sprint():
    data=dataset([task("A",hours=130,sp=13),task("B",hours=20,sp=2)],dependencies=[("A","B")])
    settings=PlanRequest()
    plan=build_plan(data,settings)
    assert rows(plan)["A"]["finish"]==2
    assert rows(plan)["B"]["start"]==3
    assert sum(c["sp"] for c in rows(plan)["A"]["chunks"])==pytest.approx(13)
    assert sum(a["hours"] for a in plan["allocations"] if a["task_id"]=="A")==pytest.approx(130)
    assert_limits(plan,data,settings)


def test_shared_person_and_absence():
    data=dataset([task("A","T",80),task("B","U",80)],
                 [engineer("E","T",.5),engineer("E","U",.5)],velocity=100)
    settings=PlanRequest(availability={"E":{1:0,2:.5}})
    plan=build_plan(data,settings)
    assert all(a["sprint"]>1 for a in plan["allocations"])
    assert_limits(plan,data,settings)


def test_failed_task_releases_every_resource():
    data=dataset([task("A",hours=1000,sp=100,priority=20),task("B",hours=80,sp=8)])
    plan=build_plan(data,PlanRequest())
    assert rows(plan)["A"]["code"]=="horizon"
    assert rows(plan)["B"]["start"]==1
    assert all(a["task_id"]=="B" for a in plan["allocations"])


def test_missing_role_does_not_consume_sp():
    a=task();a.roles={"qa":10}
    data=dataset([a])
    plan=build_plan(data,PlanRequest())
    assert rows(plan)["A"]["code"]=="missing_role"
    assert not plan["allocations"]


def test_skills_are_explicit_and_filter_engineers():
    data=dataset()
    assert rows(build_plan(data,PlanRequest(strict_skills=True)))["A"]["code"]=="unknown_skills"
    settings=PlanRequest(strict_skills=True,overrides={"A":TaskOverride(required_skills={"dev":["java"]})})
    assert rows(build_plan(data,settings))["A"]["code"]=="missing_skills"
    settings.overrides["A"].required_skills={"dev":["python"]}
    assert rows(build_plan(data,settings))["A"]["status"]=="planned"


def test_zero_remaining_never_means_done():
    a=task();a.status="InProgress";a.spent={"dev":80}
    assert rows(build_plan(dataset([a]),PlanRequest()))["A"]["status"]=="needs_input"


def test_cycle_and_overallocated_profiles_rejected():
    with pytest.raises(ValueError,match="Цикл"):
        validate_dataset(dataset([task("A"),task("B")],dependencies=[("A","B"),("B","A")]))
    with pytest.raises(ValueError,match="доля"):
        validate_dataset(dataset(engineers=[engineer("E","T"),engineer("E","U")]))


def test_facts_move_chain_without_changing_baseline():
    data=dataset([task("A"),task("B",hours=20,sp=2)],dependencies=[("A","B")])
    settings=PlanRequest()
    baseline=build_plan(data,settings)
    fact=SprintFact(sprint=1,tasks=[dict(task_id="A",status="InProgress",remaining_hours={"dev":80},remaining_sp=8)])
    facts=validate_fact(data,settings,[],fact)
    plan=build_plan(data,settings,facts)
    assert rows(plan)["B"]["start"]>rows(baseline)["B"]["start"]
    assert all(a["sprint"]>1 for a in plan["allocations"])
    result=metrics(data,settings,facts,baseline,plan)
    assert result["sprints"][0]["planned_sp"]==8
    assert result["sprints"][0]["actual_sp"]==0


def test_fact_dependencies_done_once_and_order():
    data=dataset([task("A"),task("B")],dependencies=[("A","B")])
    settings=PlanRequest()
    with pytest.raises(ValueError,match="предшественники"):
        validate_fact(data,settings,[],SprintFact(sprint=1,tasks=[dict(task_id="A",status="Done"),dict(task_id="B",status="Done")]))
    facts=validate_fact(data,settings,[],SprintFact(sprint=1,tasks=[dict(task_id="A",status="Done")]))
    with pytest.raises(ValueError,match="уже завершена"):
        validate_fact(data,settings,facts,SprintFact(sprint=2,tasks=[dict(task_id="A",status="Done")]))
    with pytest.raises(ValueError,match="по порядку"):
        validate_fact(data,settings,[],SprintFact(sprint=3))


def test_bus_factor_counts_unique_people_and_missing_skills():
    data=dataset(engineers=[engineer("E","T",.5),engineer("E","U",.5)])
    settings=PlanRequest(overrides={"A":TaskOverride(required_skills={"dev":["rust"]})})
    star=star_map(data,settings,build_plan(data,settings))
    assert len(star["engineers"])==1
    assert next(s for s in star["skills"] if s["scope"]=="Все команды" and s["skill"]=="python")["bus_factor"]==1
    assert next(s for s in star["skills"] if s["scope"]=="Все команды" and s["skill"]=="rust")["bus_factor"]==0


def test_multiple_roles_all_have_to_fit():
    a=task(hours=10,sp=4);a.roles={"dev":10,"qa":160}
    qa=Engineer(id="Q",team="T",role="qa",grade="Middle",skills=[],rate=.5)
    data=dataset([a],[engineer(),qa],velocity=100)
    plan=build_plan(data,PlanRequest())
    assert rows(plan)["A"]["finish"]==4
    assert_limits(plan,data,PlanRequest())


def test_sp_limit_is_not_the_hours_limit():
    data=dataset([task(hours=10,sp=20)],velocity=10)
    plan=build_plan(data,PlanRequest())
    assert rows(plan)["A"]["finish"]==3
    assert_limits(plan,data,PlanRequest())


def test_snapshot_cannot_use_future_data():
    with pytest.raises(ValueError,match="Начало"):
        build_plan(dataset(),PlanRequest(start_date=date(2025,1,1)))


def test_zero_kpi_denominator():
    data=dataset();settings=PlanRequest();base=build_plan(data,settings)
    result=metrics(data,settings,[],base,base)
    assert result["sprints"][1]["percent"] is None


def test_no_plan_allocations_after_quarter():
    data=dataset();settings=PlanRequest()
    facts=[{"sprint":s,"tasks":[]} for s in range(1,7)]
    result=build_plan(data,settings,facts)
    assert not result["allocations"] and not result["loads"]
    assert rows(result)["A"]["code"]=="horizon"
