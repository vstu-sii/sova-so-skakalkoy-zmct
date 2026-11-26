"""Rebuild lab 5 reports from saved observations, without any model call."""
import json
import hashlib
import time
from pathlib import Path

import nbformat
from ml.final_eval import historical_common, logic, projected_event
from ml.dataset import model_input
from tests.evals.metrics import calculate

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "docs/experiments/lab5-run"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def put(path, text):
    (ROOT / path).write_text(text, encoding="utf-8")


def fraction(m):
    return f"{m['k']}/{m['n']} ({100*m['value']:.1f}%)" if m["n"] else "нет наблюдений"


def quality_table(variants):
    table = ["| Вариант | M2 ↓ | M3 ↑ | M6 ↓ | E3 ↑ | S1 ↑ | p50 / p95, с |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name, observations in variants.items():
        m = calculate(observations)
        cells = [fraction(m[key]) for key in ("M2", "M3", "M6", "E3", "S1")]
        cells.append(f"{m['E1']['p50_ms']/1000:.2f} / {m['E1']['p95_ms']/1000:.2f}")
        table.append("| " + " | ".join([name, *cells]) + " |")
    return "\n".join(table)


def main():
    variants = {name: rows(RUN / name / "requests.jsonl") for name in (
        "delivery_before", "final", "no_prompt", "no_calendar", "no_guards")}
    metrics = {name: calculate(observations) for name, observations in variants.items()}
    dataset = rows(ROOT / "docs/quality/golden-dataset/v3.jsonl")
    for name, observations in variants.items():
        metadata = load(RUN / name / "run.json")
        if ({r["id"] for r in observations} != {r["id"] for r in dataset}
                or len(observations) != len(dataset)):
            raise ValueError("incomplete or duplicate full run")
        if metadata["source_sha256"] != hashlib.sha256(
            (ROOT / "services/extractor/llm_logic.py").read_bytes()
        ).hexdigest():
            raise ValueError("run no longer corresponds to current inference source")
    final = metrics["final"]
    baseline = metrics["delivery_before"]

    def admitted(name):
        m = metrics[name]
        return (m["M2"]["value"] < baseline["M2"]["value"]
                and all(m[key]["value"] >= baseline[key]["value"] for key in ("M3", "E3", "S1"))
                and m["M6"]["value"] <= baseline["M6"]["value"])

    chosen = "final" if admitted("final") else "no_prompt" if admitted("no_prompt") else "delivery_before"
    selection = dict(
        selected_variant=chosen,
        service_version={"final": "lab5-v3", "no_prompt": "lab5-guarded",
                         "delivery_before": "delivery_before"}[chosen],
        basis="Retrospective selection on the full corpus, not an independent holdout",
        criteria="M2 lower; M3/E3/S1 not lower; M6 not higher than delivery_before",
        source_sha256=hashlib.sha256((ROOT / "services/extractor/llm_logic.py").read_bytes()).hexdigest(),
    )
    (RUN / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    selected = selection["selected_variant"]
    deployed = metrics[selected]
    dev_dir = ROOT / "docs/experiments/lab5-dev"
    dev = {name: rows(dev_dir / name / "requests.jsonl") for name in ("delivery_before", "final")}
    history = rows(ROOT / "docs/quality/reports/lab3-full/requests.jsonl")
    lab4 = rows(ROOT / "docs/experiments/lab4-run/C_calendar/requests.jsonl")
    old_ids = {r["id"] for r in history}
    history_table = quality_table({
        "Лаба 3, 3B, 53 записи × 3": historical_common(history),
        "Лаба 4, 3B, 6 dev": historical_common(lab4),
        "Лаба 5, 1.5B, прежние 53 записи × 1": [r for r in variants[selected] if r["id"] in old_ids],
        "Лаба 5, 1.5B, все 55 записей × 1": variants[selected],
    })
    field_table = ["| Поле | Точность |", "|---|---:|"]
    field_table += [f"| {field} | {fraction(value)} |" for field, value in deployed["M1"].items()]
    test_rows = [r for r in variants[selected] if r.get("split") == "test"]
    test_metrics = calculate(test_rows)
    total_calls = sum(len(r) for r in variants.values()) + sum(len(r) for r in dev.values())
    output_limits = sum(r.get("done_reason") == "length" for r in variants[selected])
    overlong = sum(r["over_delivery_input_limit"] for r in variants[selected])
    full_table = quality_table(variants)
    dev_table = quality_table(dev)
    scenario = load(RUN / "scenario.json") if (RUN / "scenario.json").exists() else []
    scenario_table = ["| Режим /extract | HTTP | Задержка, с | Вход / выход | Цена во входе «Бесплатно» |",
                      "|---|---:|---:|---:|---:|"]
    for row in scenario:
        scenario_table.append(f"| {row['version']} | {row['status']} | {row['latency_ms']/1000:.3f} | "
            f"{row['input_tokens']:.0f} / {row['output_tokens']:.0f} | {row['response']['price']} |")
    metadata = load(RUN / selected / "run.json")
    replay_variants = {}
    indexed = {row["id"]: row for row in dataset}
    if selected == "no_prompt":
        for label, source_name, calendar, guards in (
            ("selected_without_calendar", "delivery_before", False, True),
            ("selected_without_guards", "no_prompt", True, False),
        ):
            replay = []
            for observation in variants[source_name]:
                value = observation | {"variant": label, "reused_inference_from": source_name}
                if observation["status"] == "ok":
                    inputs = model_input(indexed[observation["id"]])
                    parsed = logic.LLMFields.model_validate_json(observation["raw_response"]).model_dump()
                    started = time.perf_counter()
                    result = logic.finalize(parsed, inputs["text"], inputs["reference_date"],
                                            calendar=calendar, guards=guards)
                    value.update(event=projected_event(result), delivery_output=result,
                                 replay_postprocess_ms=(time.perf_counter()-started)*1000)
                replay.append(value)
            replay_variants[label] = replay
            folder = RUN / label
            folder.mkdir(exist_ok=True)
            (folder / "requests.jsonl").write_text("".join(
                json.dumps(r, ensure_ascii=False) + "\n" for r in replay), encoding="utf-8")
            (folder / "metrics.json").write_text(json.dumps(
                calculate(replay), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (folder / "run.json").write_text(json.dumps({
                "execution": "replay of recorded model responses",
                "new_provider_calls": 0, "inherited_latency_and_usage": True,
                "source_name": source_name,
                "source_sha256": hashlib.sha256((RUN / source_name / "requests.jsonl").read_bytes()).hexdigest(),
            }, indent=2) + "\n", encoding="utf-8")
    selected_ablation = quality_table({selected: variants[selected], **replay_variants})
    selected_contributions = []
    for label, observations in replay_variants.items():
        without = calculate(observations)
        delta = without["M2"]["k"] - deployed["M2"]["k"]
        selected_contributions.append(
            f"- {label}: M2 без компонента {fraction(without['M2'])}, "
            f"с компонентом {fraction(deployed['M2'])}. Разница {delta:+d} карточек."
        )
    summaries = {}
    for name, observations in variants.items():
        usages = [r.get("usage") for r in observations if r.get("usage")]
        summaries[name] = dict(
            input_tokens=sum(u["input_tokens"] for u in usages),
            output_tokens=sum(u["output_tokens"] for u in usages),
            measured_requests=len(usages), requests=len(observations),
        )
    cost_rows = ["| Вариант | Входные токены | Выходные токены | Учет / запросы |",
                 "|---|---:|---:|---:|"]
    for name, summary in summaries.items():
        cost_rows.append(f"| {name} | {summary['input_tokens']} | {summary['output_tokens']} | "
                         f"{summary['measured_requests']}/{summary['requests']} |")

    put("docs/ml-final-metrics.md", f"""# Финальные метрики AI. Лабораторная 5

Рабочая основа — Delivery `16e3f70`, модель `qwen2.5:1.5b` локально через
Ollama. Измеряется общий с Delivery код запроса и постобработки
`services/extractor/llm_logic.py`. Исходные ответы, CSV с latency/токенами,
версии, digest весов и SHA-256 исходников сохранены в
`docs/experiments/lab5-run/`. Это эксперимент на текущей машине.

## Полный финальный прогон

Выбран рабочий вариант **{selected}**, режим Delivery
**{selection['service_version']}**. Его M2 = {fraction(deployed['M2'])},
M3 = {fraction(deployed['M3'])}, M6 = {fraction(deployed['M6'])}.
Промежуточный кандидат final с новым промптом v3 не прошёл общий критерий
приёмки из-за ухудшения M6 и S1. Все его результаты сохранены в таблице.

Golden dataset v3 содержит 55 записей. Каждая отправлена один раз,
включая 22 test-записи. По действующей методике записи needs_context
исполняются и сохраняются, но исключаются из основных знаменателей.
Все успешные ответы оцениваются по поддерживаемым полям title,
date_start, time_start, venue и price. date_end, price_discount,
registration и media отсутствуют в четырёхполном контракте Delivery.

{full_table}

M1 для финального варианта:

{chr(10).join(field_table)}

На test-части M2 = {fraction(test_metrics['M2'])},
M3 = {fraction(test_metrics['M3'])}, E3 = {fraction(test_metrics['E3'])}.
Обрезанные ответы рабочего варианта: {output_limits}. Текстов длиннее 1500 символов:
{overlong}. В эксперименте текст не обрезается. Если такое ограничение
превышено, это отмечено в каждом результате.

## Динамика

{history_table}

Динамика пересчитана по общей проекции полей. В лабе 3 были 3 повтора,
в лабе 4 только 6 dev-примеров, сейчас 1 повтор. Модель и публичный
контракт менялись. Поэтому эти точки описывают историю проекта,
а чистый вклад последних изменений оценивается парой delivery_before
и final на одной модели и одинаковом наборе. Повторы старых данных
не являются независимыми анонсами.
Переход Delivery на 1.5B продиктован ограничениями сервера с 4 ГБ RAM.
Он не был выбран по результатам этого сравнения как более точная модель.
S1 исторических контуров проверяет строки во всём их выходе, поэтому при
смене структуры ответа его нельзя трактовать как чистый прирост защиты.

## Latency и стоимость

Фактические задержки включают HTTP к Ollama, обработку её ответа и
постобработку. keep_alive=0 означает выгрузку модели после вызова,
поэтому в задержки входит её загрузка. Прогоны последовательные и порядок
вариантов фиксирован. Внешняя плата за токены — 0 ₽. Электроэнергия,
серверный тариф и амортизация не измерялись.

{chr(10).join(cost_rows)}

Показанные суммы относятся только к ответам с известным учетом.
Если число measured_requests меньше requests, итог — нижняя оценка.
Ошибки модели учитываются как ошибки, regex-fallback в данном измерении
не маскирует их. Прогон ядра не включает JWT, PostgreSQL, очередь,
публикации, почту и браузер. Отдельная интеграционная проверка HTTP
показывает совместимость, но не является замером продового сервера.

Всего в dev и полном ablation выполнено {total_calls} запросов ядра.
Дополнительно выполнены {len(scenario)} реальных запроса к Ollama через
HTTP-обработчик /extract с тестовым ASGI-транспортом:

{chr(10).join(scenario_table)}

Авторизация подменена на синтетического владельца, зависимость БД
отключена, потому что /extract не сохраняет данные. Остальной обработчик,
бюджет и вызов Ollama реальные. На обоих запросах source=ollama.
Первый запрос может быть медленнее из-за прогрева, по этой паре
нельзя делать вывод об ускорении. Внешняя API-плата обоих запросов — 0 ₽.

S1 измеряется по запрещённым маркерам. M4/M5, приемка человеком и S2
по реальным публикациям этим экспериментом не измерены.
""")

    contribution = ["| Отключено | M2 без / с | Вклад в снижение M2 |",
                    "|---|---:|---:|"]
    interpretations = []
    for name in ("no_prompt", "no_calendar", "no_guards"):
        delta = metrics[name]["M2"]["k"] - final["M2"]["k"]
        contribution.append(f"| {name} | {metrics[name]['M2']['k']} / {final['M2']['k']} | {delta:+d} карточек |")
        direction = "уменьшил" if delta > 0 else "увеличил" if delta < 0 else "не изменил"
        field_changes = ", ".join(
            f"{field} {value['k'] - metrics[name]['M1'][field]['k']:+d}"
            for field, value in final["M1"].items()
        )
        interpretations.append(f"- По сравнению с {name} включённый компонент {direction} "
            f"число критических ошибок на {abs(delta)}. Разница верных полей: {field_changes}.")
    changed = {}
    for row in variants["final"]:
        for field in row.get("postprocessing_changes", []):
            changed.setdefault(field, []).append(row["id"])
    put("docs/experiments/lab5.md", f"""# Ablation и последняя миля. Лабораторная 5

Кандидат с новым промптом первоначально выбран на dev-части v3, затем
исходники заморожены для полного прогона. Полный прогон отклонил этот
кандидат из-за ухудшения S1/M6. По ablation принято итоговое решение
**{selected}**. Это ретроспективный выбор по тому же набору, включая
test-часть, поэтому она не является независимым подтверждением выбора.
Дополнительного изменения текста промпта после dev не было.
Набор содержит регрессии из прошлых работ и уже знаком разработчикам.

## До и после на dev

{dev_table}

## Отключение по одному

Итоговый режим lab5-guarded использует исходный промпт, календарь и проверки.
Для него выполнено отключение оставшихся компонентов:

{selected_ablation}

{chr(10).join(selected_contributions)}

Эти два контроля повторно обрабатывают сохранённые сырые ответы.
При отключении календаря взяты ответы delivery_before, полученные без
календарной подсказки, затем применены те же проверки выхода.
При отключении проверок взяты ответы no_prompt с календарной подсказкой,
затем выполнена обработка без проверок. Новых обращений к модели нет,
latency и токены в этих контролях унаследованы от исходного вызова,
а не измерены заново. replay_postprocess_ms относится только к локальным правилам.

Отдельно сохранён первоначальный живой ablation полного кандидата v3:

{full_table}

{chr(10).join(contribution)}

{chr(10).join(interpretations)}

Правила постобработки изменили значения в следующих случаях:
{json.dumps(changed, ensure_ascii=False)}.

- no_prompt убирает только дополнительные инструкции v3, оставляя календарь
  и проверки выхода. Измеряется вклад промпта при включённых других мерах.
- no_calendar отключает доверенную подсказку дня недели и перезапись даты.
- no_guards отключает проверки месяца без дня, неизвестного места,
  времени без источника и бесплатного входа.
- delivery_before отключает все три группы, сохраняя схему и параметры.

Эффекты могут взаимодействовать и не обязаны складываться.
Отрицательное значение вклада означает, что отключение уменьшило M2.
Одна попытка на пример даёт ограниченную оценку вклада.
Вместе с M2 нужно смотреть M3/M6/E3 и точность каждого поля.

## Что не сработало

Промпт v3 на dev уменьшил число критических ошибок на одну карточку,
но на полном наборе ухудшил M6 и S1. В качестве рабочего режима он
отклонён. Доступен отдельным экспериментальным флагом для повторения
ablation. Текущее решение сохранено в lab5-run/selection.json.

В лабе 4 удаление схемы из промпта уменьшило токены с 5533 до 2419,
но увеличило критические ошибки с 2/6 до 4/6. Эта оптимизация не включена.
В нынешнем контракте отсутствует отдельная регистрация и льготная цена,
поэтому сравнивать их точность со старым API нельзя.
Постобработка поддерживает только явно распознаваемые конструкции.
Она не исправляет все адреса и названия и не доказывает отсутствие инъекций.

## Подтверждение точечных фиксов

Относительная дата, месяц без числа, неизвестное место, отсутствие времени
и бесплатный вход проверены отдельными регрессионными тестами.
Их модельный эффект сохраняется в postprocessing_changes каждой записи,
а сравнение no_guards показывает вклад группы на том же наборе.
Чистое влияние каждого правила отдельно от остальных не измерялось.

Команды:

```bash
python -m ml.final_eval --variants delivery_before final --split dev
python -m ml.final_eval --split all --output docs/experiments/lab5-run
python -m ml.final_report
```

Ноутбук `lab5-experiments.ipynb` читает сохранённые файлы.
В `run.json` зафиксированы версия Python {metadata['python']},
Ollama {metadata['runtime'].get('version')}, веса и SHA-256 кода.
""")
    notebook = nbformat.v4.new_notebook(
        metadata={"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
        cells=[
            nbformat.v4.new_markdown_cell("# Лабораторная 5\nФинальные метрики и ablation по сохранённым данным. "
                "Команда живого прогона из корня: `python -m ml.final_eval --split all --output docs/experiments/lab5-run`."),
            nbformat.v4.new_code_cell("""import json
from pathlib import Path
run = Path("lab5-run")
if not run.exists():
    run = Path("docs/experiments/lab5-run")
metrics = {}
selection = json.loads((run/"selection.json").read_text(encoding="utf-8"))
print("Рабочий вариант:", selection["selected_variant"], selection["service_version"])
for name in ("delivery_before", "final", "no_prompt", "no_calendar", "no_guards"):
    metrics[name] = json.loads((run/name/"metrics.json").read_text(encoding="utf-8"))
    print(name, {k: f"{metrics[name][k]['k']}/{metrics[name][k]['n']}"
                 for k in ("M2", "M3", "M6", "E3", "S1")})"""),
            nbformat.v4.new_code_cell("""for name in ("no_prompt", "no_calendar", "no_guards"):
    print(name, "M2 contribution:", metrics[name]["M2"]["k"] - metrics["final"]["M2"]["k"])
for name in metrics:
    rows = [json.loads(line) for line in (run/name/"requests.jsonl").read_text(encoding="utf-8").splitlines()]
    print(name, "observations:", len(rows), "known tokens:",
          sum(r.get("usage", {}).get("input_tokens",0)+r.get("usage", {}).get("output_tokens",0) for r in rows))
    assert len(rows) == 55"""),
            nbformat.v4.new_markdown_cell("Отрицательный вклад — ухудшение. Выборка и модель отличаются от лаб 3–4. "
                "Полный денежный TCO и реальные публикации не измерены."),
        ],
    )
    nbformat.validate(notebook)
    nbformat.write(notebook, ROOT / "docs/experiments/lab5-experiments.ipynb")


if __name__ == "__main__":
    main()
