"""Детерминированное планирование: SP и часы проверяются одновременно."""
from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from statistics import mean
from .schemas import Dataset, PlanRequest, SprintFact

EPS = 1e-7


def initial_remaining(task, settings):
    override = settings.overrides.get(task.id)
    hours = {r:max(0, h-task.spent.get(r, 0)) for r,h in task.roles.items()}
    sp = task.sp  # Консервативно: потраченные часы не означают выполненные SP.
    if override:
        if override.remaining_hours is not None:
            hours = dict(override.remaining_hours)
        if override.remaining_sp is not None:
            sp = override.remaining_sp
    return {r:h for r,h in hours.items() if h > EPS}, sp


def snapshot(data, settings, facts):
    remaining = {t.id:initial_remaining(t, settings) for t in data.tasks}
    done = {t.id:0 for t in data.tasks if t.status == "Done"}
    for raw in sorted(facts, key=lambda x:x["sprint"]):
        fact = SprintFact.model_validate(raw)
        for item in fact.tasks:
            if item.status == "Done":
                done[item.task_id] = fact.sprint
                remaining[item.task_id] = ({}, 0)
            else:
                remaining[item.task_id] = (dict(item.remaining_hours), item.remaining_sp)
    return remaining, done


def validate_settings(data, settings):
    ids = {t.id for t in data.tasks}
    people = {e.id for e in data.engineers}
    if set(settings.overrides)-ids or set(settings.availability)-people:
        raise ValueError("В настройках неизвестный task_id или engineer_id")
    known_roles = {r for t in data.tasks for r in t.roles} | {e.role for e in data.engineers}
    for o in settings.overrides.values():
        if set(o.required_skills)-known_roles or (o.remaining_hours is not None and set(o.remaining_hours)-known_roles):
            raise ValueError("Неизвестная роль в настройках; используйте названия из данных")
    observed = [h.date for h in data.history]
    observed += [d for t in data.tasks for d in (t.created, t.actual_end) if d]
    if observed and settings.start_date < max(observed):
        raise ValueError(f"Начало должно быть не раньше {max(observed)}: файл является готовым срезом, а не архивом состояний")


def capacities(data, facts):
    teams = sorted({t.team for t in data.tasks} | {e.team for e in data.engineers})
    samples = {team:[h.achieved for h in data.history if h.team == team] for team in teams}
    tasks = {t.id:t for t in data.tasks}
    for raw in facts:
        achieved = defaultdict(float)
        for f in raw["tasks"]:
            if f["status"] == "Done":
                achieved[tasks[f["task_id"]].team] += tasks[f["task_id"]].sp
        for team in teams:
            samples[team].append(achieved[team])
    return {team:mean(values)*0.8 if values else 0 for team, values in samples.items()}


def build_plan(data: Dataset, settings: PlanRequest, facts: list[dict] | None = None):
    validate_settings(data, settings)
    facts = facts or []
    remaining, completed = snapshot(data, settings, facts)
    first = max((f["sprint"] for f in facts), default=0) + 1
    caps = capacities(data, facts)
    tasks = {t.id:t for t in data.tasks}
    parents = defaultdict(list)
    for a,b in data.dependencies:
        parents[b].append(a)
    group_priority = defaultdict(float)
    for t in data.tasks:
        group_priority[t.initiative] = max(group_priority[t.initiative], t.priority)
    used_sp = defaultdict(float)
    used_hours = defaultdict(float)
    used_person = defaultdict(float)
    results = {}
    all_allocations = []
    visiting = set()

    def result(tid, status, reason, code, chunks=None):
        t = tasks[tid]
        chunks = chunks or []
        finish = max((c["sprint"] for c in chunks), default=None)
        results[tid] = dict(task_id=tid, initiative=t.initiative, title=t.title, team=t.team,
                            status=status, code=code, reason=reason, priority=t.priority,
                            remaining_sp=remaining[tid][1], remaining_hours=sum(remaining[tid][0].values()),
                            start=min((c["sprint"] for c in chunks), default=None), finish=finish,
                            finish_date=str(settings.start_date+timedelta(days=finish*14-1)) if finish else None,
                            chunks=chunks)

    def eligible(t, role):
        override = settings.overrides.get(t.id)
        required = override.required_skills.get(role) if override else None
        if required is None and settings.strict_skills:
            return [], "unknown_skills", f"Не подтверждены требования к стеку для роли «{role}»"
        candidates = [e for e in data.engineers if e.team == t.team and e.role == role]
        if not candidates:
            return [], "missing_role", f"В {t.team} нет роли «{role}»"
        if required is not None:
            candidates = [e for e in candidates if set(required).issubset(e.skills)]
        if not candidates:
            return [], "missing_skills", f"Нет исполнителя роли «{role}» с навыками {', '.join(required or [])}"
        # Сначала более специализированный профиль, чтобы сохранить универсальных людей.
        return sorted(candidates, key=lambda e:(len(e.skills), e.id)), None, None

    def free(e, sprint, local_hours, local_person):
        availability = settings.availability.get(e.id, {}).get(sprint, 1)
        return max(0, min(80*e.rate*availability-local_hours[(sprint,e.id,e.team)],
                          80*availability-local_person[(sprint,e.id)]))

    def schedule(tid):
        if tid in results:
            return
        if tid in visiting:
            raise ValueError("Цикл зависимостей")
        visiting.add(tid)
        t = tasks[tid]
        if tid in completed:
            result(tid, "done", "Подтверждено завершение", "done")
            results[tid]["finish"] = completed[tid]
            visiting.remove(tid)
            return
        earliest = first
        for parent in sorted(parents[tid]):
            schedule(parent)
            previous = results[parent]
            if previous["status"] not in ("done", "planned"):
                result(tid, "deferred", f"Предшественник {parent}: {previous['reason']}", "dependency")
                visiting.remove(tid)
                return
            earliest = max(earliest, (previous["finish"] or 0)+1)
        hours, sp = remaining[tid]
        if not hours or sp <= EPS:
            result(tid, "needs_input", "Статус не Done, но остаток часов или SP равен нулю. Уточните остаток или внесите факт завершения", "unknown_remaining")
            visiting.remove(tid)
            return
        candidates = {}
        for role in sorted(hours):
            people, code, reason = eligible(t, role)
            if code:
                result(tid, "deferred", f"{reason}; требуется {hours[role]:g} ч", code)
                visiting.remove(tid)
                return
            candidates[role] = people
        # Пробное размещение: если квартала не хватило, возвращаем все ресурсы задачи.
        local_sp, local_hours, local_person = deepcopy(used_sp), deepcopy(used_hours), deepcopy(used_person)
        fraction_left = 1.0
        chunks, assignments = [], []
        limiting = "граница квартала после зависимостей"
        for sprint in range(earliest, 7):
            bounds = [(fraction_left, "остаток"),
                      (max(0,caps[t.team]-local_sp[(sprint,t.team)])/sp, f"SP: лимит {caps[t.team]:g} за спринт")]
            for role, required in hours.items():
                available = sum(free(e,sprint,local_hours,local_person) for e in candidates[role])
                bounds.append((available/required, f"роль «{role}»: доступно {available:g} ч, полный остаток {required:g} ч"))
            fraction, limiting = min(bounds, key=lambda x:x[0])
            if fraction <= EPS:
                continue
            chunk_roles = {}
            for role, required in hours.items():
                take = required*fraction
                chunk_roles[role] = take
                for e in candidates[role]:
                    amount = min(take, free(e,sprint,local_hours,local_person))
                    if amount > EPS:
                        local_hours[(sprint,e.id,e.team)] += amount
                        local_person[(sprint,e.id)] += amount
                        assignments.append(dict(task_id=tid, sprint=sprint, engineer_id=e.id, team=e.team, role=role, hours=amount))
                        take -= amount
            local_sp[(sprint,t.team)] += sp*fraction
            chunks.append(dict(sprint=sprint, sp=sp*fraction, hours=sum(chunk_roles.values()), roles=chunk_roles))
            fraction_left -= fraction
            if fraction_left <= EPS:
                break
        if fraction_left > EPS:
            result(tid, "deferred", f"Не вошло в найденный план до конца 6-го спринта; ограничение: {limiting}. Осталось {fraction_left*100:.1f}% работы", "horizon")
        else:
            used_sp.update(local_sp)
            used_hours.update(local_hours)
            used_person.update(local_person)
            all_allocations.extend(assignments)
            result(tid, "planned", f"Приоритет {t.priority:g}; проверены SP, роли, часы и предшественники" +
                   ("; стек подтверждён" if settings.strict_skills else "; неполные требования к стеку требуют уточнения"), "scheduled", chunks)
        visiting.remove(tid)

    for task in sorted(data.tasks, key=lambda t:(-group_priority[t.initiative], -t.priority, t.id)):
        schedule(task.id)
    initiatives = []
    for iid in sorted({t.initiative for t in data.tasks}):
        rows = [r for r in results.values() if r["initiative"] == iid]
        feasible = all(r["status"] in ("done", "planned") for r in rows)
        initiatives.append(dict(id=iid, feasible=feasible, done=all(r["status"]=="done" for r in rows),
                                planned_tasks=sum(r["status"]=="planned" for r in rows),
                                blocked_tasks=[r["task_id"] for r in rows if r["status"] not in ("done","planned")]))
    loads = [dict(sprint=s, team=team, sp=used_sp[(s,team)], capacity=cap) for s in range(first,7) for team,cap in caps.items()]
    return dict(start_date=str(settings.start_date), end_date=str(settings.start_date+timedelta(days=83)),
                first_open_sprint=first, strict_skills=settings.strict_skills,
                tasks=list(results.values()), initiatives=initiatives, loads=loads,
                allocations=all_allocations, capacities=caps)
