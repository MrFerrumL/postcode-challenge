from collections import defaultdict
from .planner import snapshot


def star_map(data, settings, plan):
    skills = defaultdict(set)
    employees = {}
    for e in data.engineers:
        employee = employees.setdefault(e.id, dict(id=e.id, role=e.role, grade=e.grade, skills=e.skills, assignments=[]))
        employee["assignments"].append(dict(team=e.team, rate=e.rate, hours_per_sprint=80*e.rate))
        for skill in e.skills:
            skills[("Все команды",skill)].add(e.id)
            skills[(e.team,skill)].add(e.id)
    # Включаем также требования, которыми никто не владеет: BF=0.
    tasks = {t.id:t for t in data.tasks}
    required_by = defaultdict(set)
    for tid,o in settings.overrides.items():
        for required in o.required_skills.values():
            for skill in required:
                for scope in ("Все команды", tasks[tid].team):
                    skills[(scope,skill)]
                    required_by[(scope,skill)].add(tid)
    factors = [dict(scope=scope, skill=skill, bus_factor=len(ids), engineers=sorted(ids),
                    tasks=sorted(required_by[(scope,skill)])) for (scope,skill),ids in skills.items()]
    factors.sort(key=lambda r:(r["bus_factor"],r["scope"],r["skill"]))
    return dict(engineers=list(employees.values()), skills=factors, allocations=plan["allocations"], availability=settings.availability)


def metrics(data, settings, facts, baseline, plan):
    if not baseline:
        return {"confirmed":False, "quarter_percent":None, "sprints":[], "message":"Сначала подтвердите исходный план"}
    _,done = snapshot(data, settings, facts)
    original_tasks = {r["task_id"] for r in baseline["tasks"] if r["status"]=="planned"}
    initiatives = {t.initiative for t in data.tasks if t.id in original_tasks}
    achieved = [iid for iid in initiatives if all(t.id in done for t in data.tasks if t.initiative==iid)]
    projected = sum(r["feasible"] for r in plan["initiatives"] if r["id"] in initiatives)
    tasks = {t.id:t for t in data.tasks}
    sprints = []
    for s in range(1,7):
        planned = sum(c["sp"] for t in baseline["tasks"] for c in t["chunks"] if c["sprint"]==s)
        fact = next((f for f in facts if f["sprint"]==s), None)
        actual = sum(tasks[t["task_id"]].sp for t in fact["tasks"] if t["status"]=="Done") if fact else None
        sprints.append(dict(sprint=s, planned_sp=planned, actual_sp=actual,
                            percent=100*actual/planned if actual is not None and planned else None))
    return dict(confirmed=True, baseline_initiatives=len(initiatives), completed_initiatives=len(achieved),
                quarter_percent=100*len(achieved)/len(initiatives) if initiatives else None,
                forecast_percent=100*projected/len(initiatives) if initiatives else None,
                sprints=sprints, message="Факт SP учитывается один раз, при Done. Плановые доли SP распределены по спринтам; Say/Do может превышать 100%.")


def risks(plan, baseline, data):
    items = []
    before = {t["task_id"]:t for t in baseline["tasks"]} if baseline else {}
    for t in plan["tasks"]:
        if t["status"] in ("deferred","needs_input"):
            level = "red" if t["code"] in ("horizon","dependency") else "orange"
            items.append(dict(level=level, task_id=t["task_id"], initiative=t["initiative"], message=t["reason"]))
        old = before.get(t["task_id"])
        if old and old["finish"] and t["finish"] and t["finish"]>old["finish"]:
            items.append(dict(level="yellow", task_id=t["task_id"], initiative=t["initiative"],
                              message=f"Сдвиг завершения: спринт {old['finish']} → {t['finish']}; проверьте зависимые работы"))
    for i in plan["initiatives"]:
        if not i["feasible"]:
            items.append(dict(level="red", task_id=None, initiative=i["id"], message="Инициатива не завершается в найденном квартальном плане: " + ", ".join(i["blocked_tasks"])))
    return items
