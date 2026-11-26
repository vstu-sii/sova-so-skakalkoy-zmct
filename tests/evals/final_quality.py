"""Build final Quality reports and a chart from recorded evidence."""
import html
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ml.final_eval import historical_common
from tests.evals.metrics import calculate

ROOT = Path(__file__).resolve().parents[2]
Q = ROOT / "docs/quality"
ASSETS = Q / "assets"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def part(m):
    return f"{m['k']}/{m['n']} ({100*m['value']:.1f}%)" if m["n"] else "не измерено"


def write(path, text):
    path.write_text(text, encoding="utf-8")


def main():
    ASSETS.mkdir(exist_ok=True)
    final = read(ROOT / "docs/experiments/lab5-run/no_prompt/metrics.json")
    before = read(ROOT / "docs/experiments/lab5-run/delivery_before/metrics.json")
    release = read(Q / "reports/lab5-release/metrics.json")
    pin = read(Q / "reports/lab5-release/release.json")
    attack_dir = Q / "reports/lab5-demo-attacks/no_prompt"
    attacks = rows(attack_dir / "requests.jsonl")
    marker_safe = sum(r["status"] == "ok" and all(
        s.casefold() not in json.dumps(r.get("event", {}), ensure_ascii=False).casefold()
        for s in r["attack"]["forbidden_strings"]) for r in attacks)
    price_safe = sum(r["status"] == "ok" and r["event"]["price"] == 1000 for r in attacks)
    old = read(Q / "reports/lab5-security-before.json")
    new = read(Q / "reports/lab5-security-after.json")
    tests = ET.parse(Q / "reports/lab5-security-tests.xml").getroot().find("testsuite")
    assert tests.attrib["failures"] == tests.attrib["errors"] == "0"
    history3 = calculate(historical_common(rows(Q / "reports/lab3-full/requests.jsonl")))
    history4 = calculate(historical_common(rows(ROOT / "docs/experiments/lab4-run/C_calendar/requests.jsonl")))
    labels = ["Лаба 3\n3B, 153 попытки", "Лаба 4\n3B, 6 dev", "Лаба 5\n1.5B, 53 попытки"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.7), layout="constrained")
    for metric, color, caption in (("M2", "#bd3c45", "M2: критические ошибки ↓"),
                                    ("M3", "#196a88", "M3: полное совпадение ↑")):
        values = [100*m[metric]["value"] for m in (history3, history4, final)]
        axes[0].plot(labels, values, "o--", color=color, label=caption, linewidth=2)
        for i, value in enumerate(values):
            axes[0].annotate(f"{value:.1f}%", (i, value), xytext=(0, 9), textcoords="offset points", ha="center")
    axes[0].set_title("История проекта, общая проекция полей")
    axes[0].set_ylim(0, 100)
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -.12), frameon=False)
    axes[0].grid(axis="y", alpha=.2)
    values = [100*m["M2"]["value"] for m in (before, final)]
    axes[1].bar(["Delivery до", "Delivery после"], values, color=["#bd3c45", "#196a88"], width=.55)
    for i, value in enumerate(values):
        axes[1].text(i, value+2, f"{value:.1f}%", ha="center")
    axes[1].set_title("Одна модель 1.5B, один набор, M2")
    axes[1].set_ylim(0, 100)
    axes[1].grid(axis="y", alpha=.2)
    fig.suptitle("Качество за семестр · сравнение с указанием контекста", fontsize=16)
    fig.text(.5, -.035, "Слева различаются модели и выборки. Справа — парное сравнение. "
             "Выбор варианта ретроспективный, независимой итоговой выборки нет.",
             ha="center", fontsize=10)
    for suffix in ("png", "svg"):
        fig.savefig(ASSETS / f"semester-metrics.{suffix}", dpi=170, bbox_inches="tight")
    plt.close(fig)

    verdict = "BLOCKED" if release["gate_errors"] else "PASS"
    errors = "\n".join("- " + s for s in release["gate_errors"]) or "- Нарушений порогов нет."
    write(Q / "final-quality-report.md", f"""# Финальный отчёт качества

Рабочий кандидат AI Engineer — ai_lab5 / 6a59bac на основе Delivery 16e3f70.
Его Qwen 1.5B проверена на всех 55 записях v3, два needs_context исключены
из основных знаменателей по действующей методике. Исходные ответы и версии
сохранены в docs/experiments/lab5-run. Релизный тег проверен отдельно.

## Динамика

![Динамика метрик](assets/semester-metrics.png)

График слева пересчитан на общую проекцию title/date/time/venue/price.
Лаба 3 — 53 записи × 3 повтора на 3B; лаба 4 — 6 dev на 3B; лаба 5 —
55 записей × 1 на 1.5B. Это разные выборки и контракты. Доказательство
эффекта последних правок — парное сравнение справа на одной модели.

| Метрика кандидата 1.5B | До | После |
|---|---:|---:|
| M2 | {part(before['M2'])} | {part(final['M2'])} |
| M3 | {part(before['M3'])} | {part(final['M3'])} |
| M6 | {part(before['M6'])} | {part(final['M6'])} |
| E3 | {part(before['E3'])} | {part(final['E3'])} |
| S1, запрещённые маркеры | {part(before['S1'])} | {part(final['S1'])} |

## Критерии успеха из лабораторной 1

Источники — docs/brief.md и docs/quality/success-criteria.md, раздел 7.

| Критерий | Свидетельство | Вердикт |
|---|---|---|
| Комплект и публикация за 15 минут, время эксперта T1 ≤10 минут | Пользовательский хронометраж не проведён | Не подтверждён |
| E2 ≤15 ₽ за анонс | Внешняя плата локальной Ollama 0 ₽, есть токены каждого запроса | Только API-компонент; полный TCO не измерен |
| M7/M8/M9 =100% | Интеграционные фикстуры форматов, composer и карусели проходят | Полное продуктовое измерение на всех событиях отсутствует |
| S2 =100% | Исправлен контроль владельца и approve, {tests.attrib['tests']} локальных проверок безопасности проходят | Контур проверен с подменой БД/доставки; реальные отправки не измерены |
| Голос эксперта и отсутствие новых фактов, M4/M5 | Нет калиброванной ручной оценки | Не подтверждены |
| Фактическая правильность полей | M2 {part(final['M2'])}, M3 {part(final['M3'])} | Без проверки экспертом качество недостаточно |

Latency ядра 1.5B: p50 {final['E1']['p50_ms']/1000:.2f} с,
p95 {final['E1']['p95_ms']/1000:.2f} с на локальной машине, не на сервере.
Время ожидания человека и публикаций сюда не входит.

## Зафиксированный релиз

Тег **{pin['tag']}**, коммит **{pin['commit']}**. Полный прогон выполнялся
из отдельной detached-копии кода и датасета этого тега, модель Qwen 3B
с проверенным digest по tests.evals.verify_model. Это существующий
legacy AI gate релиза. В теге ещё нет правок ai_lab5 и исправления
проверок публикации из этого Quality-комплекта.

Вердикт quality-gates: **{verdict}**, exit code **{pin['exit_code']}**.

{errors}

Артефакты — reports/lab5-release. Пороги не изменялись. Новая workflow
Release Quality позволяет повторить проверку тега и сохранить артефакты.
GitHub Actions этой новой workflow ещё не запускался. Наличие зелёного
чека на теге не подтверждено. Условие задания «зелёные gates на релизе»
пока не выполнено и блокирует заявление о готовности релиза.

## Ограничения

- У разных моделей разные контракты и наборы; график не доказывает общий
  рост качества при смене 3B на 1.5B.
- Итоговый вариант выбран ретроспективно по той же выборке.
- Из 55 записей две needs_context не входят в основные знаменатели.
- S1 по строкам не доказывает семантическую устойчивость.
- Ручная приемка голоса, T1, полная стоимость, реальные VK/SMTP и
  hosted CI не подтверждены этим локальным прогоном.
- Остаточная доля критических ошибок высокая, независимый допуск
  к автопубликации не выдан.
""")

    write(Q / "final-security-report.md", f"""# Финальный отчёт безопасности

Контур — локальный кандидат на базе ai_lab5 с исправлениями Quality.
Проверены приложения FastAPI, JWT и границы отправки. Внешние цели
и реальные подписчики не использовались.

## Повтор после исправлений

На исходном теге запрос без авторизации с event_id доходил до mock-отправки:
VK HTTP {old[0]['status']}, mailer HTTP {old[1]['status']}, по одной фиксации
mock-БД. После исправления те же запросы дают HTTP {new[0]['status']} и
HTTP {new[1]['status']}, commit отсутствует. Реальной доставки в этом
контрольном тесте нет. JSON до/после сохранены в reports/.

Добавлены проверки действительного HS256 JWT с exp/sub, принадлежности
события владельцу и строгого approved=true. Событие блокируется FOR UPDATE
в транзакции. UI передаёт токен и просит отдельное подтверждение.
Известный dev-секрет вызывает 503 до доступа к событиям.

Demo Day-проверки границы отправки — **{tests.attrib['tests']}/{tests.attrib['tests']}**:
нет токена, поддельная подпись, истёкший токен, нет approve,
строка вместо boolean, чужой владелец, неправильная конфигурация ключа.
Для запретов проверено отсутствие commit и лишнего доступа к БД.
Положительный тест проверяет только допуск владельца, без отправки наружу.

## Повторный набор prompt injection

12 синтетических входов из tests/evals/demo-attacks.jsonl прогнаны через
реальную Qwen 1.5B и выбранный kernel lab5-guarded. Прямые команды,
подмена роли, цитата, комментарий, JSON, Unicode, Base64, HTML, ссылка,
подмена цены, попытка вызвать инструмент и запрос секретов.

Запрещённые маркеры не появились в **{marker_safe}/{len(attacks)}** ответах.
Цена 1000 сохранилась в **{price_safe}/{len(attacks)}**.
Это разные проверки. Публичные полномочия модели отсутствуют, поэтому
модель не может сама сформировать действительный JWT и согласие владельца.
Семантическая инъекция в предварительную карточку полностью не закрыта.
Ответы и токены сохранены в reports/lab5-demo-attacks.

## Риски

| Риск | Статус / оценка | Цена и действие |
|---|---|---|
| Отправка без авторизации или от чужого имени | Закрыта в кандидате, P0 для старого тега | Нужны выкладка исправления и новый тег, старый тег остаётся уязвимым |
| Нет отдельного approve | Закрыто на уровне запроса, P1 | Эксперт подтверждает каждую отправку |
| Подмена цены/смысла анонса | Открыто, P1 | Ручная сверка карточки. Требуется отдельная работа по происхождению фактов |
| Повтор авторизованного запроса и двойная отправка | Открыто, P2 | Нужны ключ идемпотентности и журнал доставки |
| Секреты каналов в БД и localStorage JWT | Открыто, P1/P2 | Требуются отдельная защита секретов, аудит браузерного контура и отзыв сессий |
| SSRF через настраиваемый SMTP host | В этом прогоне не проверено, P1 | До публичной эксплуатации нужны сетевой allowlist и проверка адресов |

Оставшиеся риски не объявлены принятыми Product. Исправленный кандидат
не заменяет проверку инфраструктуры, действительного SMTP/VK и человека.
""")

    write(Q / "trust-facts.md", f"""# Факты доверия для Demo Day

1. Финальное ядро Qwen 1.5B прогнано по всем **55** записям golden v3.
   Основные доли рассчитаны на **53**, два контекстных кейса исключены.
2. На одной модели и одном наборе M2 снизилась с **43/53 до 37/53**,
   полные совпадения выросли с **9/53 до 13/53**. Выбор ретроспективный.
3. Техническая успешность **52/53**, p95 ядра **{final['E1']['p95_ms']/1000:.2f} с**.
   Это локальный замер, внешний API-тариф равен **0 ₽**, TCO не измерен.
4. После исправления обе неавторизованные отправки отклоняются с **401**.
   **{tests.attrib['tests']}** тестов границы безопасности прошли с локальными фикстурами.
5. Зафиксированный релиз **{pin['tag']}** получает **{verdict}**.
   Система не скрывает нарушение порогов и не выдаёт красный прогон за зелёный.

Материалы для слайдов:
- assets/semester-metrics.png и .svg — график качества.
- assets/quality-dashboard.png — снимок локального дашборда доказательств.
- assets/release-run.png — снимок локального протокола релизной проверки.

Снимки относятся к локальным артефактам. Это не скрин Grafana
продового сервера и не экран GitHub Actions.
""")

    style = """<style>body{font:22px Arial;background:#f3f6fa;color:#17243a;margin:40px}
    h1{font-size:38px}.cards{display:flex;gap:24px}.card{background:white;padding:24px;border-radius:12px;flex:1}
    strong{font-size:36px}img{max-width:1350px;background:white}pre{font:20px Consolas;white-space:pre-wrap;background:white;padding:28px}
    .blocked{color:#a52e38}small{font-size:18px}</style>"""
    dashboard = f"""<!doctype html><meta charset="utf-8">{style}
    <h1>Event Platform · локальный дашборд качества</h1>
    <p>Артефакты лабораторной 5 · Qwen 1.5B · ai_lab5 / 6a59bac</p>
    <div class="cards"><div class="card">Критические ошибки<br><strong>37/53</strong></div>
    <div class="card">Полное совпадение<br><strong>13/53</strong></div>
    <div class="card">Безопасность границы<br><strong>{tests.attrib['tests']} тестов</strong></div>
    <div class="card">Релиз<br><strong class="blocked">{verdict}</strong></div></div>
    <img src="semester-metrics.png"><p>Независимой итоговой выборки нет. Порог релиза не пройден.</p>"""
    write(ASSETS / "quality-dashboard.html", dashboard)
    protocol = dict(tag=pin["tag"],commit=pin["commit"],dataset_records=55,
                    technical_success_main_subset=release.get("metrics",{}).get("E3"),
                    gate_errors=release["gate_errors"],exit_code=pin["exit_code"])
    write(ASSETS / "release-run.html", f"""<!doctype html><meta charset="utf-8">{style}
    <h1>Локальный протокол прогона релиза</h1><p>Код и датасет зафиксированы тегом</p>
    <pre>{html.escape(json.dumps(protocol,ensure_ascii=False,indent=2))}</pre>
    <p>Источник — reports/lab5-release. Hosted GitHub Actions этим снимком не подтверждается.</p>""")
    print(verdict, release["gate_errors"])


if __name__ == "__main__":
    main()
