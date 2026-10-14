# synthetic_v2 – simplified MwM test package

Small, self-contained config + synthetic data: 2 countries (Syria, Sudan), 24 schools each,
4 drivers, 16 indicators, 14 dimensions. Every driver has an outcome, a quality and a quantity
indicator plus two contexts. Outcome gains are generated from implementation, so CIOs show a signal.

| Driver | Outcome | Quantity | Quality |
|---|---|---|---|
| d_01 Teacher PD | literacy | cpd_sessions_attended | teaching_quality_score |
| d_02 PSS | wellbeing | pss_sessions_delivered | pss_session_fidelity |
| d_03 Safe environment | perceived_safety | safety_lessons_delivered | safe_environment_score |
| d_04 Attendance & caregivers | child_attendance_rate | caregiver_sessions_held | caregiver_attendance_rate |

Contexts: class_size, teacher_wellbeing, shock_intensity, distance_to_school_km.

## Contents
- `generate.py` – seeded generator + validator (`python synthetic_v2\generate.py`).
- `config/indicators.csv`, `dimensions.csv` – replace `config/*_config.csv`.
- `config/drivers.csv`, `driver_indicators.csv` – driver config (source of truth for driver membership/role/report_agg).
  `indicators.csv` also carries `driver_id|driver_level|report_agg` derived from it, so the current `build_cmos` works unchanged.
- `data/` – `child_assessments`, `child_monthly`, `teacher_monthly`, `school_monthly` per country.
- `schema.sql` – **destructive**: drops/recreates the combined tables and truncates pipeline outputs.

## Load
1. Run `schema.sql` in the Supabase SQL editor.
2. Clear old config rows if you want only the new ones (`delete from indicators; delete from dimensions;`).
3. `python -m src.update_config indicators synthetic_v2/config/indicators.csv`, same for `dimensions`, `drivers`, `driver_indicators`
   (the last two need their tables created via the printed SQL if `SUPABASE_DB_URL` is unset).
4. Copy `data/*.csv` to `data/input/` (or point the notebook at it) and run the batch for drivers d_01–d_04.

## Notes
- Outcomes use `change_from_baseline` (date based). Avoid `end_minus_base`: `round` is not carried to the school table, so it is always NaN.
- `build_cmos` still reads driver membership from `indicators.csv`; `drivers`/`driver_indicators` are loaded for the planned switch.
- Notebook driver loop should cover `d_01`–`d_04` instead of `d_01`–`d_08`.
