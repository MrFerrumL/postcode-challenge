"""Демонстрационный прогноз. Не меняет жёсткие ограничения планировщика."""
from collections import defaultdict
from statistics import mean
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline


def forecast(history):
    rows = sorted(history, key=lambda h:h.date)
    if len(rows) < 2:
        return {"message":"Недостаточно истории", "teams":[], "mae":None, "baseline_mae":None, "validation_n":0}
    def model():
        return make_pipeline(DictVectorizer(sparse=False), Ridge(alpha=10))
    def x(row):
        return {"team":row.team, "planned_sp":row.planned}
    errors, baseline_errors = [], []
    # На каждой дате учимся только на более ранних датах всех команд.
    for day in sorted({h.date for h in rows}):
        train = [h for h in rows if h.date < day]
        test = [h for h in rows if h.date == day and any(p.team==h.team for p in train)]
        if len(train) < 2 or not test:
            continue
        fitted = model().fit([x(h) for h in train], [h.achieved for h in train])
        for h, predicted in zip(test, fitted.predict([x(h) for h in test])):
            errors.append(abs(max(0,float(predicted))-h.achieved))
            baseline_errors.append(abs(mean(p.achieved for p in train if p.team==h.team)-h.achieved))
    fitted = model().fit([x(h) for h in rows], [h.achieved for h in rows])
    teams = defaultdict(list)
    for h in rows:
        teams[h.team].append(h)
    predictions = []
    for team, samples in sorted(teams.items()):
        planned = samples[-1].planned
        predicted = max(0,float(fitted.predict([{"team":team,"planned_sp":planned}])[0]))
        predictions.append(dict(team=team, planned_sp=planned, predicted_sp=predicted, observations=len(samples)))
    return dict(message="Эксперимент Ridge. Мало наблюдений; planned_sp для прогноза взят из последней записи. Прогноз не меняет лимит SP.",
                teams=predictions, mae=mean(errors) if errors else None,
                baseline_mae=mean(baseline_errors) if errors else None, validation_n=len(errors))
