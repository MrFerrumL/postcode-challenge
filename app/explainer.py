"""Человеческие объяснения решений планировщика."""
from collections import Counter, defaultdict


def explain_task(task_id, plan, data, settings):
    """Возвращает объяснение решения по задаче или None."""
    tasks = {t.id:t for t in data.tasks}
    rows = {t["task_id"]:t for t in plan["tasks"]}
    task, row = tasks.get(task_id), rows.get(task_id)
    if not task or not row:
        return None
    role,hours = next(((r,h) for r,h in task.roles.items() if h > 0), ("роль", 0))
    affected = sorted(b for a,b in data.dependencies if a == task_id)
    initiatives = sorted({task.initiative} | {tasks[tid].initiative for tid in affected})
    code = row["code"]
    actions = []
    if code == "missing_role":
        nearby = next((e for e in data.engineers if e.role == role and e.team != task.team), None)
        person = f"Ближайший носитель {nearby.id} находится в {nearby.team}, но он уже загружен" if nearby else "В других командах носитель этой роли не найден"
        text = (f"Задача {task_id} «{task.title}» не может быть выполнена, потому что в команде {task.team} нет ни одного "
                f"инженера с ролью «{role}». Требуется {hours:g} часов работы этой роли. {person}.")
        actions = [f"Перевести специалиста с ролью «{role}» в {task.team} на время задачи.",
                   f"Пересмотреть приоритеты и перенести {task_id} на следующий квартал.",
                   f"Нанять специалиста с ролью «{role}» для снижения долгосрочного риска."]
    elif code == "missing_skills":
        required = settings.overrides.get(task_id).required_skills.get(role, []) if task_id in settings.overrides else []
        skills = ", ".join(required) or "подтверждённые навыки"
        text = (f"Задача {task_id} не может быть выполнена: в {task.team} есть инженеры с ролью «{role}», но ни у одного "
                f"нет требуемых навыков ({skills}). Для работы необходимо {hours:g} часов компетенции этой роли.")
        actions = [f"Подтвердить или изменить требования к стеку для {task_id} в настройках.",
                   "Перевести инженера с нужными навыками из другой команды.",
                   f"Запланировать найм специалиста с навыками: {skills}."]
    elif code == "horizon":
        limiting = row["reason"].split("ограничение:", 1)[-1].split(". Осталось", 1)[0].strip()
        text = (f"Задача {task_id} не вошла в 12-недельный горизонт квартала: после завершения предшественников не осталось "
                f"достаточно спринтов для {row['remaining_hours']:g} часов работы. Ограничение плана: {limiting}.")
        actions = [f"Повысить приоритет {task_id} и перенести менее важные задачи инициативы {task.initiative}.",
                   f"Увеличить доступность инженеров роли «{role}» в команде {task.team}.",
                   f"Перенести {task_id} на следующий квартал и сфокусироваться на ближайших задачах."]
    elif code == "dependency":
        parent = next((a for a,b in data.dependencies if b == task_id), "предшественник")
        parent_reason = rows.get(parent, {}).get("reason", "предшественник ещё не завершён")
        text = (f"Задача {task_id} не может быть начата, потому что её предшественник {parent} не завершён. Причина: "
                f"{parent_reason}. Без завершения {parent} задача {task_id} и связанные с ней работы не сдвинутся.")
        actions = [f"Устранить причину блокировки предшественника {parent}.",
                   f"Пересмотреть приоритет {task_id} в пользу незаблокированных задач {task.initiative}.",
                   f"Перенести {task_id}, если предшественник {parent} выйдет за квартал."]
    elif code == "unknown_skills":
        text = (f"Задача {task_id} требует подтверждения требований к стеку для роли «{role}» в строгом режиме. "
                "Без этих данных планировщик не может проверить, найдётся ли подходящий исполнитель и когда начнётся работа.")
        actions = [f"Подтвердить требования к стеку для {task_id} в разделе «Данные и настройки».",
                   "Отключить строгую проверку навыков, если требования пока не критичны."]
    elif code == "unknown_remaining":
        text = (f"Задача {task_id} не завершена, но остаток часов или SP равен нулю. Это может означать ошибку "
                "в данных либо незакрытый факт спринта, поэтому срок и загрузку нельзя рассчитать надёжно.")
        actions = ["Проверить факт последнего спринта: задача могла быть завершена.",
                   "Указать фактический остаток часов и SP в разделе «Уточнить задачу»."]
    elif code == "scheduled":
        text = (f"Задача {task_id} включена в план: приоритет {row['priority']:g}, начало в спринте {row['start']}, "
                f"завершение в спринте {row['finish']}. Роли, часы и предшественники проверены. Объём составляет "
                f"{row['remaining_sp']:g} SP и {row['remaining_hours']:g} часов.")
        actions = [f"Проверить факт выполнения в конце спринта {row['start']}.",
                   "Следить за загрузкой ответственных инженеров, если задача критична."]
    elif code == "done":
        text = f"Задача {task_id} завершена в спринте {row['finish']}. Она больше не потребляет плановую ёмкость команды и не блокирует связанные работы текущего квартала."
    else:
        text = f"Задача {task_id} имеет статус «{row['status']}». Планировщик отметил причину: {row['reason']}. Проверьте данные и доступность команды перед следующим пересчётом."
        actions = ["Проверить исходные данные и ограничения задачи.", "Пересчитать план после уточнения доступности команды."]
    return dict(task_id=task_id, title=task.title, team=task.team, initiative=task.initiative,
                status=row["status"], code=code, explanation=text, suggested_actions=actions,
                affected_tasks=affected, affected_initiatives=initiatives, priority=row["priority"],
                remaining_hours=row["remaining_hours"], start=row["start"], finish=row["finish"])


def explain_initiative(initiative_id, plan, data, settings):
    """Возвращает объяснение выполнимости инициативы или None."""
    initiative = next((i for i in plan["initiatives"] if i["id"] == initiative_id), None)
    if not initiative:
        return None
    rows = {t["task_id"]:t for t in plan["tasks"]}
    blocked = [dict(task_id=tid, reason=rows[tid]["reason"], code=rows[tid]["code"])
               for tid in initiative["blocked_tasks"]]
    if initiative["feasible"]:
        text = (f"Инициатива {initiative_id} укладывается в квартал: все {initiative['planned_tasks']} задач включены в план, "
                "а завершение не выходит за 12 недель. Основные ограничения для текущего набора работ закрыты.")
        actions = ["Следить за фактическим выполнением спринтов.", "Проверять риски на вкладке «Риски и ограничения»."]
    else:
        codes = ", ".join(code for code,_ in Counter(x["code"] for x in blocked).most_common(2))
        top = ", ".join(x["task_id"] for x in blocked[:3])
        text = (f"Инициатива {initiative_id} не завершится в этом квартале: {len(blocked)} задач остались заблокированными. "
                f"Основные причины — {codes}. Пока критичные задачи не разблокированы, срок инициативы нельзя подтвердить.")
        actions = [f"Разблокировать критичные задачи: {top}.",
                   f"Перенести инициативу {initiative_id} на следующий квартал, если разблокировка невозможна.",
                   "Пересмотреть приоритеты и отменить необязательную часть работ."]
    return dict(id=initiative_id, feasible=initiative["feasible"], done=initiative["done"], explanation=text,
                suggested_actions=actions, planned_tasks=initiative["planned_tasks"],
                blocked_tasks=initiative["blocked_tasks"], blocked_reasons=blocked)


def explain_engineer(engineer_id, plan, data, settings):
    """Возвращает профиль инженера и его загрузку или None."""
    profiles = [e for e in data.engineers if e.id == engineer_id]
    if not profiles:
        return None
    engineer = profiles[0]
    loads = defaultdict(float)
    tasks = defaultdict(set)
    for item in plan["allocations"]:
        if item["engineer_id"] == engineer_id:
            loads[item["sprint"]] += item["hours"]
            tasks[item["sprint"]].add(item["task_id"])
    sprint_loads = [dict(sprint=s, hours=loads[s], tasks=sorted(tasks[s])) for s in range(1,7)]
    maximum = max(sprint_loads, key=lambda x:x["hours"])
    limit = 80*sum(e.rate for e in profiles)
    warning = f"Перегрузка в спринте {maximum['sprint']}." if maximum["hours"] > limit else "Перегрузки не обнаружено."
    load_text = ", ".join(f"С{x['sprint']} {x['hours']:g} ч" for x in sprint_loads)
    text = (f"{engineer_id} — {engineer.grade} {engineer.role} в {engineer.team}, ставка {engineer.rate:g}. Владеет "
            f"{len(engineer.skills)} компетенциями. Загрузка по спринтам: {load_text}. {warning}")
    return dict(engineer_id=engineer_id, team=engineer.team, role=engineer.role, grade=engineer.grade,
                rate=engineer.rate, skills=engineer.skills, explanation=text, sprint_loads=sprint_loads,
                suggested_actions=[f"Проверить загрузку в спринте {maximum['sprint']}: {maximum['hours']:g} ч при доступных {limit:g} ч.",
                                   f"Если {engineer_id} — единственный носитель критичного навыка, проверить карту компетенций."])
