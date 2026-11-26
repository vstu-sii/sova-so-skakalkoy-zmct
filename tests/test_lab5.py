"""Regressions for the exact payload and postprocessor used by Delivery."""
import json

from ml.final_eval import logic, projected_event, projection


def output(**kwargs):
    return dict(title="Лекция", date="2026-12-01T18:00:00", location="Студия", price=None) | kwargs


def test_calendar_resolves_relative_date_and_preserves_explicit_time():
    text = "В субботу в 19:00 лекция."
    assert logic.finalize(output(date="2025-11-19T19:00:00"), text, "2025-11-14")["date"] == "2025-11-15T19:00:00"
    assert logic.calendar_hint("В субботу 20 ноября 2026", "2025-11-14") is None
    assert logic.calendar_hint("В следующую субботу", "2025-11-14") is None
    assert logic.calendar_hint("В субботу и в воскресенье", "2025-11-14") is None


def test_month_and_missing_context_are_not_invented():
    text = "Открыта запись на декабрьскую супервизию. Место как обычно."
    result = logic.finalize(output(), text, "2026-11-26")
    assert result["date"] is None and result["location"] is None
    assert logic.finalize(output(), "Лекция 1 декабря 2026", "2026-11-26")["date"] == "2026-12-01"


def test_free_and_discount_are_not_confused():
    assert logic.finalize(output(), "Лекция. Вход свободный.", "2026-11-26")["price"] == 0
    assert logic.finalize(output(price=500), "Цена 500, для детей бесплатно", "2026-11-26")["price"] == 500


def test_ablation_really_disables_each_component():
    text = "В субботу. Место как обычно. Бесплатно."
    before = output()
    assert logic.finalize(before, text, "2025-11-14", calendar=False, guards=False) == before
    assert logic.finalize(before, text, "2025-11-14", calendar=False)["date"] == "2026-12-01"
    final = logic.payload(text, "2025-11-14", "qwen2.5:1.5b")
    no_prompt = logic.payload(text, "2025-11-14", "qwen2.5:1.5b", prompt_v3=False)
    assert final["messages"] != no_prompt["messages"]
    assert final["options"] == no_prompt["options"]
    assert final["format"] == no_prompt["format"]
    assert "tools" not in final


def test_projection_does_not_score_unsupported_fields():
    row = dict(expected={"title": "Лекция", "date_end": None, "registration": "ЛС", "venue": None},
               assert_fields=["title", "date_end", "registration", "venue"])
    expected, fields = projection(row)
    assert fields == ["title", "venue"] and expected == {"title": "Лекция", "venue": None}
    assert projected_event(output(date="2026-12-01"))["time_start"] is None
