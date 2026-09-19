from collections import Counter
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.loader import load_excel

SOURCE=Path(__file__).resolve().parents[1]/"data"/"source.xlsx"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/"state.sqlite3")) as c:
        yield c


def test_original_dataset_findings():
    data=load_excel(SOURCE.read_bytes())
    assert len(data.tasks)==45
    assert len({e.id for e in data.engineers})==30
    assert len(data.dependencies)==19
    assert len(data.history)==12
    counts=Counter(i["code"] for i in data.issues)
    assert counts["hours_mismatch"]==24
    assert counts["total_mismatch"]==9
    assert counts["overrun"]==2


def test_api_complete_roundtrip_and_persistence(client):
    assert client.get("/").status_code==200
    assert client.get("/api/state").json()["empty"]
    state=client.post("/api/demo").json()
    assert len(state["plan"]["tasks"])==45
    assert Counter(t["status"] for t in state["plan"]["tasks"])["planned"]==4
    baseline=client.post("/api/baseline").json()["baseline"]
    fact={"sprint":1,"tasks":[{"task_id":"MP-102","status":"Done"}]}
    response=client.post("/api/facts",json=fact)
    assert response.status_code==200,response.text
    updated=response.json()
    assert updated["baseline"]==baseline
    assert updated["metrics"]["sprints"][0]["actual_sp"]==9
    count=len(updated["revisions"])
    replay=client.post("/api/facts",json=fact).json()
    assert len(replay["revisions"])==count
    assert replay["metrics"]["sprints"][0]["actual_sp"]==9
    assert client.get("/api/state").json()["baseline"]==baseline
    settings=updated["settings"]
    settings["availability"]={"ENG-414":{"2":0}}
    response=client.post("/api/plan",json=settings)
    assert response.status_code==200
    assert response.json()["baseline"]==baseline
    settings["start_date"]="2026-07-01"
    assert client.post("/api/plan",json=settings).status_code==400


def test_scenarios_preserve_previous_and_upload(client):
    first=client.post("/api/demo").json()
    client.post("/api/baseline")
    second=client.post("/api/upload",files={"file":("source.xlsx",SOURCE.read_bytes(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
    assert first["id"]!=second["id"]
    assert len(second["scenarios"])==2
    previous=client.post("/api/scenarios/"+first["id"]).json()
    assert previous["baseline"] is not None


def test_invalid_input_does_not_replace_current_state(client):
    state=client.post("/api/demo").json()
    for name,content in [("bad.txt",b"bad"),("bad.xlsx",b"bad")]:
        assert client.post("/api/upload",files={"file":(name,content)}).status_code==400
    assert client.get("/api/state").json()["id"]==state["id"]
    settings=state["settings"]
    settings["overrides"]={"missing":{"remaining_sp":3}}
    assert client.post("/api/plan",json=settings).status_code==400


def test_facts_require_baseline_and_validate_remaining(client):
    client.post("/api/demo")
    assert client.post("/api/facts",json={"sprint":1,"tasks":[]}).status_code==400
    client.post("/api/baseline")
    assert client.post("/api/facts",json={"sprint":1,"tasks":[{"task_id":"MP-102","status":"InProgress"}]}).status_code==422
    assert client.post("/api/facts",json={"sprint":1,"tasks":[{"task_id":"MP-102","status":"Done"},{"task_id":"MP-102","status":"Done"}]}).status_code==422


def test_ml_separate_from_plan(client):
    state=client.post("/api/demo").json()
    response=client.get("/api/ml")
    assert response.status_code==200,response.text
    result=response.json()
    assert len(result["teams"])==6
    assert result["validation_n"]>0
    assert result["mae"] is not None
    assert client.get("/api/state").json()["plan"]==state["plan"]


def test_sqlite_survives_new_app_instance(tmp_path):
    path=tmp_path/"saved.sqlite3"
    with TestClient(create_app(path)) as c:
        sid=c.post("/api/demo").json()["id"]
        c.post("/api/baseline")
    with TestClient(create_app(path)) as c:
        state=c.get("/api/state").json()
        assert state["id"]==sid and state["baseline"]
