"""API и простой интерфейс. Запуск: python -m uvicorn app.main:app."""
import os
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .analytics import build_bus_factor_report, group_risks, metrics, risks, star_map
from .diff import diff_plans, list_deferred
from .explainer import explain_engineer, explain_initiative, explain_task
from .loader import load_excel, role_name, skill_name
from .ml import forecast
from .planner import build_plan, snapshot, validate_settings
from .schemas import BusFactorReport, Dataset, History, PlanRequest, SprintFact
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent


def normalize_settings(settings):
    for override in settings.overrides.values():
        if override.remaining_hours is not None:
            override.remaining_hours = normalize_hours(override.remaining_hours)
        normalized = {}
        for role, skills in override.required_skills.items():
            key = role_name(role)
            if key in normalized:
                raise ValueError("Одна роль указана под двумя названиями")
            normalized[key] = sorted({skill_name(s) for s in skills})
        override.required_skills = normalized
    return settings


def normalize_hours(values):
    result = {}
    for role,hours in values.items():
        key = role_name(role)
        if key in result:
            raise ValueError("Одна роль указана под двумя названиями")
        result[key] = hours
    return result


def make_state(content, name):
    dataset = load_excel(content)
    dates = [h.date for h in dataset.history] + [d for t in dataset.tasks for d in (t.created,t.actual_end) if d]
    start = max(dates) if dates else PlanRequest().start_date
    # Первый понедельник не раньше всех наблюдений в срезе.
    start += timedelta(days=(-start.weekday()) % 7)
    settings = PlanRequest(start_date=start)
    return dict(name=name, dataset=dataset.model_dump(mode="json"), settings=settings.model_dump(mode="json"),
                plan=build_plan(dataset,settings), baseline=None, facts=[], revisions=[])


def validate_fact(data, settings, existing, fact):
    last = max((f["sprint"] for f in existing), default=0)
    if fact.sprint not in (last, last+1) or (last==0 and fact.sprint!=1):
        raise ValueError("Закрывайте спринты по порядку. Исправлять можно только последний закрытый спринт")
    prior = [f for f in existing if f["sprint"] < fact.sprint]
    _, done = snapshot(data, settings, prior)
    tasks = {t.id:t for t in data.tasks}
    known_roles = {r for t in data.tasks for r in t.roles} | {e.role for e in data.engineers}
    for item in fact.tasks:
        if item.task_id not in tasks:
            raise ValueError(f"Неизвестная задача {item.task_id}")
        if item.task_id in done:
            raise ValueError(f"{item.task_id} уже завершена в предыдущем периоде")
        item.remaining_hours = normalize_hours(item.remaining_hours)
        item.spent_hours = normalize_hours(item.spent_hours)
        if (set(item.remaining_hours) | set(item.spent_hours))-known_roles:
            raise ValueError("Неизвестная роль в факте")
        if item.status == "Done":
            missing = [a for a,b in data.dependencies if b==item.task_id and a not in done]
            if missing:
                raise ValueError(f"{item.task_id}: предшественники не завершены до этого спринта: {', '.join(missing)}")
    return prior + [fact.model_dump(mode="json")]


def create_app(db_path=None):
    app = FastAPI(title="Квартал — планирование команд", version="1.0.0")
    store = Store(db_path or os.environ.get("PLANNER_DB", str(ROOT/"data"/"state"/"planner.sqlite3")))
    app.state.store = store
    app.mount("/static", StaticFiles(directory=ROOT/"app"/"static"), name="static")

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse(status_code=400, content={"detail":str(exc)})

    @app.get("/")
    def index():
        return FileResponse(ROOT/"app"/"static"/"index.html")

    @app.get("/health")
    def health():
        return {"status":"ok"}

    def present(state):
        if not state:
            return {"empty":True, "scenarios":store.list()}
        data = Dataset.model_validate(state["dataset"])
        settings = PlanRequest.model_validate(state["settings"])
        plan = state["plan"]
        risks_list = risks(plan,state["baseline"],data)
        return dict(**state, empty=False, scenarios=store.list(),
                    metrics=metrics(data,settings,state["facts"],state["baseline"],plan),
                    stars=star_map(data,settings,plan), risks=risks_list, alerts=group_risks(risks_list))

    @app.get("/api/state")
    def state():
        return present(store.read())

    @app.get("/api/bus-factor", response_model=BusFactorReport)
    def bus_factor():
        state = store.read()
        if not state:
            raise ValueError("Сначала загрузите данные")
        data = Dataset.model_validate(state["dataset"])
        settings = PlanRequest.model_validate(state["settings"])
        stars = star_map(data, settings, state["plan"])
        return build_bus_factor_report(stars, data, settings)

    @app.get("/api/diff")
    def diff_endpoint():
        state = store.read()
        if not state:
            raise ValueError("Сначала загрузите данные")
        revisions = state.get("revisions", [])
        if not revisions:
            return {"empty":True, "message":"Пересчётов ещё не было. Diff появится после первого пересчёта."}
        data = Dataset.model_validate(state["dataset"])
        result = diff_plans(revisions[-1]["plan"], state["plan"], data)
        result["revision_reason"] = revisions[-1]["reason"]
        return result

    @app.get("/api/deferred")
    def deferred_endpoint():
        state = store.read()
        if not state:
            raise ValueError("Сначала загрузите данные")
        return list_deferred(state["plan"], Dataset.model_validate(state["dataset"]))

    @app.get("/api/explain/task/{task_id}")
    def explain_task_endpoint(task_id: str):
        state = store.read()
        if not state:
            raise ValueError("Сначала загрузите данные")
        data = Dataset.model_validate(state["dataset"])
        settings = PlanRequest.model_validate(state["settings"])
        result = explain_task(task_id, state["plan"], data, settings)
        if result is None:
            raise ValueError(f"Неизвестная задача {task_id}")
        return result

    @app.get("/api/explain/initiative/{initiative_id}")
    def explain_initiative_endpoint(initiative_id: str):
        state = store.read()
        if not state:
            raise ValueError("Сначала загрузите данные")
        data = Dataset.model_validate(state["dataset"])
        settings = PlanRequest.model_validate(state["settings"])
        result = explain_initiative(initiative_id, state["plan"], data, settings)
        if result is None:
            raise ValueError(f"Неизвестная инициатива {initiative_id}")
        return result

    @app.get("/api/explain/engineer/{engineer_id}")
    def explain_engineer_endpoint(engineer_id: str):
        state = store.read()
        if not state:
            raise ValueError("Сначала загрузите данные")
        data = Dataset.model_validate(state["dataset"])
        settings = PlanRequest.model_validate(state["settings"])
        result = explain_engineer(engineer_id, state["plan"], data, settings)
        if result is None:
            raise ValueError(f"Неизвестный инженер {engineer_id}")
        return result

    @app.post("/api/demo")
    def demo():
        state = make_state((ROOT/"data"/"source.xlsx").read_bytes(), "Исходный датасет")
        return present(store.create("Исходный датасет",state))

    @app.post("/api/upload")
    async def upload(file: UploadFile):
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(400,"Загрузите файл .xlsx")
        content = await file.read(5_000_001)
        await file.close()
        if len(content)>5_000_000:
            raise HTTPException(400,"Максимальный размер XLSX — 5 МБ")
        try:
            state = make_state(content, Path(file.filename).name)
        except (KeyError, TypeError, IndexError) as exc:
            raise ValueError(f"Неполная структура Excel: {exc}") from exc
        return present(store.create(state["name"], state))

    @app.post("/api/scenarios/{sid}")
    def select(sid: str):
        store.select(sid)
        return present(store.read())

    @app.post("/api/plan")
    def plan(request: PlanRequest):
        settings = normalize_settings(request)
        def update(state):
            if state["baseline"] and str(settings.start_date)!=state["baseline"]["start_date"]:
                raise ValueError("После подтверждения нельзя менять начало квартала. Создайте новый сценарий")
            data = Dataset.model_validate(state["dataset"])
            new_plan = build_plan(data, settings, state["facts"])
            state["revisions"].append({"reason":"Настройки плана", "plan":state["plan"]})
            state["settings"] = settings.model_dump(mode="json")
            state["plan"] = new_plan
        return present(store.mutate(update))

    @app.post("/api/baseline")
    def baseline():
        def update(state):
            if state["baseline"] is None:
                if not any(t["status"]=="planned" for t in state["plan"]["tasks"]):
                    raise ValueError("В плане нет задач для подтверждения")
                # Исходный план не должен меняться вместе с текущим прогнозом.
                state["baseline"] = deepcopy(state["plan"])
        return present(store.mutate(update))

    @app.post("/api/facts")
    def facts(fact: SprintFact):
        def update(state):
            if not state["baseline"]:
                raise ValueError("Сначала подтвердите исходный план")
            data = Dataset.model_validate(state["dataset"])
            settings = PlanRequest.model_validate(state["settings"])
            new_facts = validate_fact(data,settings,state["facts"],fact)
            if new_facts == state["facts"]:
                return
            state["revisions"].append({"reason":f"Факт спринта {fact.sprint}", "plan":state["plan"], "facts":state["facts"]})
            state["facts"] = new_facts
            state["plan"] = build_plan(data,settings,new_facts)
        return present(store.mutate(update))

    @app.get("/api/ml")
    def ml():
        state = store.read()
        if not state:
            raise ValueError("Сначала загрузите данные")
        data = Dataset.model_validate(state["dataset"])
        settings = PlanRequest.model_validate(state["settings"])
        tasks = {t.id:t for t in data.tasks}
        history = list(data.history)
        for fact in state["facts"]:
            for team in state["plan"]["capacities"]:
                planned = sum(c["sp"] for t in state["baseline"]["tasks"] if t["team"]==team
                              for c in t["chunks"] if c["sprint"]==fact["sprint"])
                actual = sum(tasks[f["task_id"]].sp for f in fact["tasks"] if f["status"]=="Done" and tasks[f["task_id"]].team==team)
                history.append(History(date=settings.start_date+timedelta(days=14*fact["sprint"]-1),team=team,achieved=actual,planned=planned))
        return forecast(history)

    return app


app = create_app()
