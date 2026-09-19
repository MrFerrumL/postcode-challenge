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
    task_index = {t.id:t for t in data.tasks}
    required_by = defaultdict(set)
    for tid,o in settings.overrides.items():
        for required in o.required_skills.values():
            for skill in required:
                for scope in ("Все команды", task_index[tid].team):
                    skills[(scope,skill)]
                    required_by[(scope,skill)].add(tid)
    factors = [dict(scope=scope, skill=skill, bus_factor=len(ids), engineers=sorted(ids),
                    tasks=sorted(required_by[(scope,skill)])) for (scope,skill),ids in skills.items()]
    factors.sort(key=lambda r:(r["bus_factor"],r["scope"],r["skill"]))
    plan_tasks = {t["task_id"]:t for t in plan["tasks"]}
    affected_by = defaultdict(set)
    missing_roles = defaultdict(set)
    for task in data.tasks:
        planned = plan_tasks.get(task.id)
        if task.status == "Done" or not planned:
            continue
        active = planned["status"] not in ("deferred", "needs_input")
        for role,hours in task.roles.items():
            if hours <= 0:
                continue
            holders = [e for e in data.engineers if e.team == task.team and e.role == role]
            if not any(e.role == role for e in data.engineers):
                # Дефицит роли сам переводит задачу в deferred, его нельзя скрывать этим статусом.
                missing_roles[(task.team,role)].add(task.id)
            if active:
                for holder in holders:
                    for skill in holder.skills:
                        affected_by[(task.team,skill)].add(task.id)
                        affected_by[("Все команды",skill)].add(task.id)
        if active:
            override = settings.overrides.get(task.id)
            for role,required in (override.required_skills.items() if override else []):
                if task.roles.get(role, 0) > 0:
                    for skill in required:
                        affected_by[(task.team,skill)].add(task.id)
                        affected_by[("Все команды",skill)].add(task.id)
    critical_skills = []
    for factor in factors:
        tasks = sorted(affected_by[(factor["scope"],factor["skill"])])
        bus_factor = factor["bus_factor"]
        if bus_factor == 0 or bus_factor >= 2 or (not tasks and factor["scope"] == "Все команды"):
            continue
        holder = factor["engineers"][0] if bus_factor == 1 else None
        profile = employees.get(holder, {})
        assignment = next((a for a in profile.get("assignments", []) if a["team"] == factor["scope"]),
                          profile.get("assignments", [{}])[0]) if holder else {}
        rate = assignment.get("rate", 0)
        risk_level = "critical" if tasks and (rate < .5 or len(tasks) >= 3) else "high" if tasks else "medium"
        risk_category = "parttime" if tasks and rate < .5 else "unique_skill" if risk_level == "critical" else "potential"
        initiatives = sorted({task_index[tid].initiative for tid in tasks})
        subject = holder or "нет носителя"
        reason = (f"{len(tasks)} задач из {', '.join(initiatives)} встанут" if tasks
                  else "задач с подтверждённой потребностью сейчас нет")
        holder_reason = (f"{subject} — единственный носитель компетенции «{factor['skill']}»"
                         if holder else f"нет носителя компетенции «{factor['skill']}»")
        critical_skills.append(dict(scope=factor["scope"], skill=factor["skill"], bus_factor=bus_factor,
                                    holder=holder, holder_name=holder, holder_role=profile.get("role"),
                                    holder_team=assignment.get("team"), holder_rate=assignment.get("rate"),
                                    affected_tasks=tasks, affected_initiatives=initiatives,
                                    risk_level=risk_level, risk_category=risk_category,
                                    explanation=f"{reason}, потому что в области «{factor['scope']}» {holder_reason}" +
                                                (f"; {holder} работает на {assignment['rate']:g} ставки — риск выше."
                                                 if risk_level == "high" else ".")))
    grouped_roles = defaultdict(lambda: defaultdict(set))
    for (scope,role),tasks in missing_roles.items():
        grouped_roles[role][scope].update(tasks)
    for role,scopes in grouped_roles.items():
        scope = next(iter(scopes)) if len(scopes) == 1 else "Все команды"
        tasks = set().union(*scopes.values())
        initiatives = sorted({task_index[tid].initiative for tid in tasks})
        location = f"В команде {scope}" if scope != "Все команды" else "Во всех командах"
        critical_skills.append(dict(scope=scope, skill=role, bus_factor=0, holder=None, holder_name=None,
                                    holder_role=None, holder_team=None, holder_rate=None,
                                    affected_tasks=sorted(tasks), affected_initiatives=initiatives,
                                    risk_level="critical", risk_category="role_deficit",
                                    explanation=f"{location} нет ни одного инженера с ролью «{role}» — "
                                                f"задачи {', '.join(sorted(tasks))} из {', '.join(initiatives)} "
                                                "не могут быть выполнены в этом квартале."))
    specific = {(s["skill"],s["holder"]) for s in critical_skills
                if s["holder"] and s["scope"] != "Все команды"}
    critical_skills = [s for s in critical_skills
                       if s["scope"] != "Все команды" or (s["skill"],s["holder"]) not in specific]
    critical_skills.sort(key=lambda s:(0 if s["bus_factor"] == 0 else
                                       1 if s["risk_level"] == "critical" else
                                       2 if s["risk_level"] == "high" else 3,
                                       -len(s["affected_tasks"]),s["scope"],s["skill"]))
    return dict(engineers=list(employees.values()), skills=factors, critical_skills=critical_skills,
                allocations=plan["allocations"], availability=settings.availability)


def build_bus_factor_report(stars, data, settings):
    """Собирает понятный отчёт по рискам Bus Factor."""
    critical_skills = stars["critical_skills"]
    risk_skills = {s["skill"] for s in critical_skills}
    return dict(total_skills=len(stars["skills"]),
                critical_count=sum(s["risk_level"] == "critical" for s in critical_skills),
                high_count=sum(s["risk_level"] == "high" for s in critical_skills),
                medium_count=sum(s["risk_level"] == "medium" for s in critical_skills),
                critical_skills=critical_skills,
                healthy_skills=[s for s in stars["skills"] if s["bus_factor"] >= 2 and s["skill"] not in risk_skills])


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
