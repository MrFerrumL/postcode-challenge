"""Изменения плана и причины переноса задач."""
import re


DEFERRED_CODES = ("missing_role", "missing_skills", "horizon", "dependency",
                  "unknown_skills", "unknown_remaining")


def diff_plans(old_plan, new_plan, data):
    """Сравнивает снимок плана с текущим планом."""
    old = {row["task_id"]:row for row in old_plan["tasks"]}
    new = {row["task_id"]:row for row in new_plan["tasks"]}
    shifts, added, removed = [], [], []
    for task_id, row in new.items():
        previous = old.get(task_id)
        if not previous:
            continue
        if previous["status"] == row["status"] == "planned":
            if (previous["start"], previous["finish"]) != (row["start"], row["finish"]):
                reason = f"Начало: С{previous['start']} → С{row['start']}; завершение: С{previous['finish']} → С{row['finish']}"
                shifts.append(dict(task_id=task_id, old_start=previous["start"], new_start=row["start"],
                                   old_finish=previous["finish"], new_finish=row["finish"], reason=reason))
        elif row["status"] == "planned" and previous["status"] in ("deferred", "needs_input"):
            added.append(dict(task_id=task_id, initiative=row["initiative"],
                              reason=f"Добавлена после пересчёта: {row['reason']}"))
        elif previous["status"] == "planned" and row["status"] in ("deferred", "needs_input"):
            removed.append(dict(task_id=task_id, initiative=row["initiative"], old_status=previous["status"],
                                new_status=row["status"], reason=row["reason"]))
    old_initiatives = {row["id"]:row for row in old_plan["initiatives"]}
    initiatives = [dict(id=row["id"], was_feasible=old_initiatives[row["id"]]["feasible"],
                        now_feasible=row["feasible"], blocked_tasks=row["blocked_tasks"])
                   for row in new_plan["initiatives"] if row["id"] in old_initiatives
                   and old_initiatives[row["id"]]["feasible"] != row["feasible"]]
    return dict(shifts=shifts, added=added, removed=removed, initiatives=initiatives,
                summary=dict(shifts=len(shifts), added=len(added), removed=len(removed),
                             initiatives_affected=len(initiatives)))


def list_deferred(plan, data):
    """Группирует перенесённые задачи по причине."""
    groups = {code:[] for code in DEFERRED_CODES}
    groups["other"] = []
    tasks = {task.id:task for task in data.tasks}
    for row in plan["tasks"]:
        if row["status"] not in ("deferred", "needs_input"):
            continue
        task = tasks.get(row["task_id"])
        role, hours = next(((role, hours) for role, hours in (task.roles if task else {}).items() if hours > 0),
                           (None, None))
        code = row["code"] if row["code"] in DEFERRED_CODES else "other"
        item = dict(task_id=row["task_id"], initiative=row["initiative"], team=row["team"], reason=row["reason"])
        if code in ("missing_role", "missing_skills"):
            item.update(role=role, hours=hours)
        if code == "missing_skills":
            match = re.search(r"навыками\s+(.+?)(?:;|$)", row["reason"])
            item["required_skills"] = match.group(1) if match else row["reason"]
        groups[code].append(item)
    for items in groups.values():
        items.sort(key=lambda item:item["task_id"])
    summary = {code:len(items) for code,items in groups.items()}
    summary["total"] = sum(summary.values())
    return dict(**groups, summary=summary)
