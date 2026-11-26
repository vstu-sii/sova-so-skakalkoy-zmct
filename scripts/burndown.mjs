#!/usr/bin/env node
// Burndown спринта лабы 4.
//
//   node scripts/burndown.mjs record [--date YYYY-MM-DD] [--note "текст"]
//       Считает остаток по docs/sprint/tasks.csv и записывает строку за дату
//       в docs/sprint/burndown-log.csv (по умолчанию — сегодня). Дату раньше
//       последней записи писать нельзя: лог только дополняется, задним числом
//       точки не рисуются. Повторный запуск в тот же день заменяет строку дня.
//   node scripts/burndown.mjs render
//       Перерисовывает docs/sprint/burndown.svg и блоки в docs/burndown.md.
//
// Без зависимостей, Node 18+.

import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const TASKS = join(ROOT, 'docs/sprint/tasks.csv')
const LOG = join(ROOT, 'docs/sprint/burndown-log.csv')
const SVG = join(ROOT, 'docs/sprint/burndown.svg')
const MD = join(ROOT, 'docs/burndown.md')

const SPRINT_START = '2026-11-12'
const SPRINT_END = '2026-12-09'
const ACCEPTANCE_DAYS = ['2026-11-18', '2026-11-25', '2026-12-02', '2026-12-09']
const STATUSES = new Set(['todo', 'doing', 'done', 'cut'])

// ---------- данные ----------

function readCsv(path) {
  const lines = readFileSync(path, 'utf8').replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim())
  const head = lines[0].split(';')
  return lines.slice(1).map((line, i) => {
    const cells = line.split(';')
    if (cells.length !== head.length) throw new Error(`${path}:${i + 2}: ожидалось ${head.length} полей, найдено ${cells.length}`)
    return Object.fromEntries(head.map((h, j) => [h, cells[j].trim()]))
  })
}

function loadTasks() {
  const tasks = readCsv(TASKS).map((t) => ({ ...t, estimate_h: Number(t.estimate_h), remaining_h: Number(t.remaining_h) }))
  for (const t of tasks) {
    if (!STATUSES.has(t.status)) throw new Error(`${t.id}: неизвестный статус «${t.status}»`)
    if (!(t.estimate_h > 0) || !(t.remaining_h >= 0)) throw new Error(`${t.id}: оценка и остаток должны быть числами`)
    if (t.status === 'done' && (t.remaining_h !== 0 || !t.done_on)) throw new Error(`${t.id}: у done остаток 0 и заполнен done_on`)
  }
  return tasks
}

const loadLog = () => (existsSync(LOG) ? readCsv(LOG).map((r) => ({ ...r, scope_h: Number(r.scope_h), remaining_h: Number(r.remaining_h) })) : [])

function totals(tasks) {
  const live = tasks.filter((t) => t.status !== 'cut')
  return {
    scope: live.reduce((s, t) => s + t.estimate_h, 0),
    remaining: live.filter((t) => t.status !== 'done').reduce((s, t) => s + t.remaining_h, 0),
  }
}

// ---------- календарь ----------

const iso = (d) => d.toISOString().slice(0, 10)
const ddmm = (s) => `${s.slice(8, 10)}.${s.slice(5, 7)}`

function workingDays() {
  const days = []
  for (let d = new Date(SPRINT_START + 'T00:00:00Z'); iso(d) <= SPRINT_END; d.setUTCDate(d.getUTCDate() + 1)) {
    const wd = d.getUTCDay()
    if (wd !== 0 && wd !== 6) days.push(iso(d))
  }
  return days
}

// позиция 0 — начало спринта, позиция i — конец i-го рабочего дня
function position(days, date) {
  let pos = 0
  for (const d of days) if (d <= date) pos++
  return pos
}

// ---------- record ----------

function record(args) {
  const date = args.date ?? iso(new Date())
  const note = (args.note ?? '').replaceAll(';', ',')
  if (date < SPRINT_START || date > SPRINT_END) throw new Error(`${date} вне спринта ${SPRINT_START}…${SPRINT_END}`)
  const log = loadLog()
  const last = log.at(-1)
  if (last && date < last.date) throw new Error(`последняя запись ${last.date}; писать ${date} задним числом нельзя`)
  const { scope, remaining } = totals(loadTasks())
  const row = { date, scope_h: scope, remaining_h: remaining, note }
  if (last && last.date === date) log[log.length - 1] = row
  else log.push(row)
  writeFileSync(LOG, 'date;scope_h;remaining_h;note\n' + log.map((r) => `${r.date};${r.scope_h};${r.remaining_h};${r.note}`).join('\n') + '\n')
  console.log(`${date}: скоуп ${scope} ч, осталось ${remaining} ч`)
  render()
}

// ---------- render ----------

function svg(days, log) {
  const W = 760, H = 380, L = 56, R = 20, T = 36, B = 64
  const n = days.length
  const scope0 = log[0]?.scope_h ?? 0
  const yStep = 20
  const yMax = Math.max(yStep, Math.ceil(Math.max(scope0, ...log.map((r) => r.scope_h)) / yStep) * yStep)
  const x = (p) => L + (p / n) * (W - L - R)
  const y = (v) => T + (1 - v / yMax) * (H - T - B)
  const out = []
  out.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" font-family="Segoe UI, Arial, sans-serif" font-size="11">`)
  out.push(`<rect width="${W}" height="${H}" fill="#ffffff"/>`)
  out.push(`<text x="${L}" y="20" font-size="14" font-weight="600" fill="#1f2328">Burndown спринта лабы 4 — оставшиеся часы</text>`)
  for (let v = 0; v <= yMax; v += yStep) {
    out.push(`<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#e6e8eb"/>`)
    out.push(`<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" fill="#57606a">${Math.round(v)}</text>`)
  }
  for (const d of ACCEPTANCE_DAYS) {
    const px = x(position(days, d))
    out.push(`<line x1="${px}" x2="${px}" y1="${T}" y2="${H - B}" stroke="#c9a0dc" stroke-dasharray="2 3"/>`)
    out.push(`<text x="${px}" y="${T - 4}" text-anchor="middle" fill="#8250df" font-size="10">приёмка ${ddmm(d)}</text>`)
  }
  for (let p = 0; p <= n; p++) {
    const label = p === 0 ? 'старт' : ddmm(days[p - 1])
    if (p % 2 === 0 || p === n) out.push(`<text x="${x(p)}" y="${H - B + 16}" text-anchor="end" transform="rotate(-45 ${x(p)} ${H - B + 16})" fill="#57606a">${label}</text>`)
    out.push(`<line x1="${x(p)}" x2="${x(p)}" y1="${H - B}" y2="${H - B + 4}" stroke="#8c959f"/>`)
  }
  out.push(`<line x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}" stroke="#8c959f"/>`)
  if (log.length) {
    out.push(`<line x1="${x(0)}" y1="${y(scope0)}" x2="${x(n)}" y2="${y(0)}" stroke="#8c959f" stroke-width="1.5" stroke-dasharray="6 4"/>`)
    const pts = [[0, scope0], ...log.map((r) => [position(days, r.date), r.remaining_h])]
    out.push(`<polyline fill="none" stroke="#0969da" stroke-width="2.5" points="${pts.map(([p, v]) => `${x(p)},${y(v)}`).join(' ')}"/>`)
    for (const [p, v] of pts) out.push(`<circle cx="${x(p)}" cy="${y(v)}" r="3.5" fill="#0969da"/>`)
    const sc = [[0, scope0], ...log.map((r) => [position(days, r.date), r.scope_h])]
    if (sc.some(([, v]) => v !== scope0)) out.push(`<polyline fill="none" stroke="#bf8700" stroke-width="1.5" points="${sc.map(([p, v]) => `${x(p)},${y(v)}`).join(' ')}"/>`)
  }
  const ly = H - 14
  out.push(`<line x1="${L}" x2="${L + 24}" y1="${ly}" y2="${ly}" stroke="#0969da" stroke-width="2.5"/><text x="${L + 30}" y="${ly + 4}" fill="#1f2328">факт (из burndown-log.csv)</text>`)
  out.push(`<line x1="${L + 210}" x2="${L + 234}" y1="${ly}" y2="${ly}" stroke="#8c959f" stroke-width="1.5" stroke-dasharray="6 4"/><text x="${L + 240}" y="${ly + 4}" fill="#1f2328">идеальная линия</text>`)
  out.push(`<line x1="${L + 360}" x2="${L + 384}" y1="${ly}" y2="${ly}" stroke="#bf8700" stroke-width="1.5"/><text x="${L + 390}" y="${ly + 4}" fill="#1f2328">скоуп (если менялся)</text>`)
  out.push('</svg>')
  return out.join('\n') + '\n'
}

function summary(days, log) {
  if (!log.length) return '_Записей ещё нет: запустите `node scripts/burndown.mjs record`._'
  const n = days.length
  const scope0 = log[0].scope_h
  const last = log.at(-1)
  const p = position(days, last.date)
  const ideal = Math.round(scope0 * (1 - p / n) * 10) / 10
  const dev = Math.round((last.remaining_h - ideal) * 10) / 10
  const burned = last.scope_h - last.remaining_h
  const pace = p ? Math.round((burned / p) * 10) / 10 : 0
  const need = n - p ? Math.round((last.remaining_h / (n - p)) * 10) / 10 : 0
  return [
    `| Показатель | Значение |`,
    `|---|---|`,
    `| Последняя запись | ${ddmm(last.date)} (рабочий день ${p} из ${n}) |`,
    `| Скоуп | ${last.scope_h} ч (на старте ${scope0} ч) |`,
    `| Осталось | ${last.remaining_h} ч |`,
    `| По идеальной линии | ${ideal} ч |`,
    `| Отклонение | ${dev > 0 ? '+' : ''}${dev} ч ${dev > 0 ? '(отстаём)' : dev < 0 ? '(опережаем)' : ''} |`,
    `| Фактический темп | ${pace} ч / рабочий день |`,
    `| Нужный темп до конца | ${need} ч / рабочий день |`,
  ].join('\n')
}

function tasksTable(tasks) {
  const mark = { todo: '☐', doing: '◐', done: '☑', cut: '✂' }
  return [
    '| ID | Задача | Роль | Скоуп | Оценка, ч | Осталось, ч | Статус | Закрыта |',
    '|---|---|---|---|---:|---:|---|---|',
    ...tasks.map((t) => `| ${t.id} | ${t.title} | ${t.role} | ${t.scope} | ${t.estimate_h} | ${t.remaining_h} | ${mark[t.status]} ${t.status} | ${t.done_on ? ddmm(t.done_on) : ''} |`),
  ].join('\n')
}

function logTable(log) {
  return ['| Дата | Скоуп, ч | Осталось, ч | Комментарий |', '|---|---:|---:|---|', ...log.map((r) => `| ${ddmm(r.date)} | ${r.scope_h} | ${r.remaining_h} | ${r.note} |`)].join('\n')
}

function replaceBlock(text, name, body) {
  const re = new RegExp(`(<!-- ${name}:start -->)[\\s\\S]*?(<!-- ${name}:end -->)`)
  if (!re.test(text)) throw new Error(`в docs/burndown.md нет блока ${name}`)
  return text.replace(re, `$1\n${body}\n$2`)
}

function render() {
  const days = workingDays()
  const tasks = loadTasks()
  const log = loadLog()
  writeFileSync(SVG, svg(days, log))
  let md = readFileSync(MD, 'utf8')
  md = replaceBlock(md, 'summary', summary(days, log))
  md = replaceBlock(md, 'tasks', tasksTable(tasks))
  md = replaceBlock(md, 'log', logTable(log))
  writeFileSync(MD, md)
  console.log('docs/burndown.md и docs/sprint/burndown.svg обновлены')
}

// ---------- cli ----------

const [cmd, ...rest] = process.argv.slice(2)
const args = {}
for (let i = 0; i < rest.length; i += 2) args[rest[i].replace(/^--/, '')] = rest[i + 1]
try {
  if (cmd === 'record') record(args)
  else if (cmd === 'render') render()
  else console.log('Использование: node scripts/burndown.mjs record [--date YYYY-MM-DD] [--note "..."] | render')
} catch (e) {
  console.error('Ошибка:', e.message)
  process.exit(1)
}
