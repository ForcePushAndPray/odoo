# Ukraine — HR KPI Scorecard

Модуль української локалізації Odoo 19.0 для оцінки KPI співробітників, ведення збалансованих scorecard'ів та автоматичного нарахування бонусів.

## Призначення

`l10n_ua_hr_scorecard` дозволяє:

- вести довідник KPI з двома методами розрахунку (бінарний і коефіцієнт виконання),
- формувати **scorecard** для кожного працівника на період (квартал / рік) з кількома KPI, де сума ваг дорівнює 100%,
- обчислювати зважений результат, який може бути більшим або меншим за 100%,
- зберігати індивідуальний **спліт компенсації** (зарплата / бонус) для кожного співробітника у окремому довіднику,
- **автоматично нараховувати бонуси** у вигляді записів `hr.bonus` за двома моделями виплат (по закінченні періоду або щомісячні аванси з реконсиляцією).

Модуль **самодостатній**: не модифікує і не успадковує моделі інших `l10n_ua_*` модулів. Бонуси створюються як інстанси `hr.bonus` (модель з `l10n_ua_hr_salary_bonus`), сам же `hr.bonus` залишається незмінним.

## Залежності

| Модуль | Призначення |
|---|---|
| `l10n_ua_hr_base` | Групи доступу `group_hr_ua_officer`, `group_hr_ua_manager` |
| `l10n_ua_hr_salary_bonus` | Моделі `hr.bonus`, `hr.bonus.type` для нарахування |

## Моделі

| Модель | Опис |
|---|---|
| `hr.kpi` | Довідник KPI. Поля: `name`, `code`, `calculation_method` (`binary`/`coefficient`), `higher_is_better`, `uom_name`, `company_id`. |
| `hr.kpi.period` | Період оцінки (`quarter` / `year`), стани `open` → `closed`. Має дію `action_accrue_bonuses` для масового нарахування. |
| `hr.scorecard.employee.config` | **Per-employee налаштування**: `salary_pct` + `bonus_pct` (сума = 100%), `bonus_base`, `bonus_model`, `bonus_type_id`. Один запис на (співробітник, компанія). |
| `hr.scorecard` | Scorecard працівника на період. Lifecycle `draft` → `confirmed` → `closed`. Computed `weighted_result`, `bonus_amount`. M2M `bonus_ids` до створених `hr.bonus`. |
| `hr.scorecard.line` | KPI-рядок scorecard: `weight`, `planned_value`/`actual_value`/`binary_achieved`, computed `achievement`, `weighted_achievement`. |

## Розрахунок KPI

- **Binary** — `100%` якщо `binary_achieved`, інакше `0%`.
- **Coefficient** — `actual_value / planned_value × 100%`; якщо `higher_is_better=False`, інвертується (`planned/actual`).
- **Weighted result scorecard'у** — `Σ (achievement_i × weight_i / 100)`. Може бути меншим або більшим за 100%.
- **Сума бонусу** — `bonus_base × weighted_result / 100`.

## Моделі виплат бонусу

### 1. Period-based (`period`)

Один разовий бонус після закриття scorecard.

- Передумова: `state == 'closed'`.
- Дія: створює один `hr.bonus(amount=bonus_amount, date=period.date_to)`.
- Прапор: `final_accrued=True`. Повторне натискання — no-op (ідемпотентно).

### 2. Monthly advance with reconciliation (`monthly_advance`)

Щомісячні аванси + остаточна реконсиляція.

- На `state == 'confirmed'`:
  - створюється N авансів `hr.bonus(amount=bonus_base / N, date=кінець місяця)`,
  - `advances_accrued=True`.
- На `state == 'closed'`:
  - створюється бонус-реконсиляція `hr.bonus(amount=bonus_amount − Σ авансів, date=period.date_to)` (може бути від’ємним за перевиплати),
  - `final_accrued=True`.

Усі створені `hr.bonus` лишаються у стані `draft`. Підтвердження робить HR-фахівець через стандартний інтерфейс `HR → Bonuses` модуля `l10n_ua_hr_salary_bonus` (бо `hr.bonus.action_confirm()` перевіряє `employee.bonus_system_enabled`).

## Робочий процес

1. **Налаштування KPI**: `HR → KPI Scorecards → Configuration → KPIs` — створити довідник KPI.
2. **Створення періоду**: `Configuration → Periods` — додати квартал/рік.
3. **Спліт працівника**: `Employee KPI Configs` — задати `salary_pct`/`bonus_pct`, дефолтні `bonus_base`, `bonus_model`, `bonus_type_id`.
4. **Scorecard**: `Scorecards → New` — обрати працівника й період, додати KPI-рядки з вагами (сума = 100%), вказати фактичні значення.
5. **Confirm**: для `monthly_advance` — натискання `Accrue Bonus` створює аванси.
6. **Close** (після кінця періоду): натискання `Accrue Bonus` створює фінальний бонус (period) або реконсиляцію (monthly_advance).
7. **Масове нарахування**: на формі періоду — кнопка `Accrue Bonuses`, що обробляє всі confirmed/closed scorecard'и періоду.

Створені бонуси доступні через smart-button **Bonuses** на scorecard або через стандартне меню Bonuses модуля зарплати.

## Меню

```
HR
└── KPI Scorecards
    ├── Scorecards
    ├── Employee KPI Configs           (officer+)
    └── Configuration                  (manager only)
        ├── KPIs
        └── Periods
```

## Права доступу

| Група | KPI / Period / Scorecard / Config | Дії |
|---|---|---|
| `hr.group_hr_user` | усі моделі | read |
| `l10n_ua_hr_base.group_hr_ua_officer` | KPI Period, Scorecard, Scorecard Line, Employee Config | read/write/create |
| `l10n_ua_hr_base.group_hr_ua_manager` | усі моделі | повний доступ |

Multi-company правила обмежують видимість записів за `company_id`.

## Обмеження (constraints)

- **Total weight = 100%** на scorecard у стані `confirmed`/`closed` — інакше `ValidationError`.
- **Salary + Bonus shares = 100%** на `hr.scorecard.employee.config` — інакше `ValidationError`.
- **Унікальність config** — один запис на (employee, company).
- **Унікальність scorecard** — один на (employee, period, company).
- **Reset to draft** заборонено, якщо вже є нараховані `hr.bonus` (треба спочатку скасувати самі бонуси).

## Установка

```bash
./odoo-bin -d <db> -i l10n_ua_hr_scorecard --stop-after-init
```

Оновлення після правок:

```bash
./odoo-bin -d <db> -u l10n_ua_hr_scorecard --stop-after-init
```

## Demo-дані

Установлення з `--demo` додає три приклади KPI (`Sales Target`, `Customer Visits`, `Quarterly Report Submitted`) та один квартальний період `Q1 2026`.

## Структура модуля

```
l10n_ua_hr_scorecard/
├── __init__.py
├── __manifest__.py
├── data/
│   └── ir_sequence_data.xml
├── demo/
│   └── hr_scorecard_demo.xml
├── models/
│   ├── __init__.py
│   ├── hr_kpi.py
│   ├── hr_kpi_period.py
│   ├── hr_scorecard.py
│   ├── hr_scorecard_employee_config.py
│   └── hr_scorecard_line.py
├── security/
│   ├── hr_scorecard_security.xml
│   └── ir.model.access.csv
└── views/
    ├── hr_kpi_views.xml
    ├── hr_kpi_period_views.xml
    ├── hr_scorecard_views.xml
    ├── hr_scorecard_employee_config_views.xml
    └── menu_views.xml
```

## Ліцензія

LGPL-3.
