"""Generate the simplified MwM synthetic package.

Run from the repo root:
    .venv\\Scripts\\python synthetic_v2\\generate.py

Writes:
    synthetic_v2/config/{indicators,dimensions,drivers,driver_indicators}.csv
    synthetic_v2/data/{child_assessments,child_monthly,teacher_monthly,school_monthly}_{country}.csv
    synthetic_v2/schema.sql
Then runs a consistency check (config <-> data).
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
SEED = 42
N_SCHOOLS = 24
CLASSES_PER_SCHOOL = 2
CHILDREN_PER_CLASS = 12
MONTHS = pd.period_range("2025-09", "2026-03", freq="M")
COUNTRIES = {
    "Syria": {"code": "SY", "admin1": ["Aleppo", "Idlib", "Homs"]},
    "Sudan": {"code": "SD", "admin1": ["Khartoum", "Darfur", "Kassala"]},
}

# --------------------------------------------------------------------------
# Config (driver_indicators is the source of truth; indicators.csv also carries
# compatibility columns driver_id/driver_level/report_agg for the current build_cmos)
# --------------------------------------------------------------------------
DRIVERS = [
    ("d_01", "Teacher professional development", "Teachers attend CPD and coaching that improves classroom practice and learning.", "school"),
    ("d_02", "Psychosocial support", "Children receive regular, good-quality PSS sessions that improve wellbeing.", "school"),
    ("d_03", "Safe learning environment", "Safety lessons and a protective school environment improve perceived safety.", "school"),
    ("d_04", "Attendance and caregiver engagement", "Caregiver sessions engage families and improve attendance.", "school"),
]

# id, level, agg_type, columns, calc_op, calc_by, label, description
INDICATORS = [
    ("literacy", "child", "simple", "literacy_score", "", "", "Literacy score", "Reading assessment score (0-100)"),
    ("wellbeing", "child", "calculated", "wb_happy,wb_calm,wb_hopeful", "mean", "", "Wellbeing", "Mean of three wellbeing items (1-5)"),
    ("perceived_safety", "child", "simple", "safety_feeling", "", "", "Perceived safety", "How safe the child feels at school (1-4)"),
    ("child_attendance_rate", "child", "calculated", "days_attended", "divide", "days_enrolled", "Attendance rate", "Days attended / days enrolled"),
    ("cpd_sessions_attended", "teacher", "simple", "cpd_sessions", "", "", "CPD sessions attended", "CPD sessions the teacher attended this month"),
    ("teaching_quality_score", "teacher", "simple", "teaching_quality", "", "", "Teaching quality", "Classroom observation score (0-100)"),
    ("class_size", "teacher", "simple", "class_size", "", "", "Class size", "Learners in the class"),
    ("teacher_wellbeing", "teacher", "simple", "teacher_wellbeing", "", "", "Teacher wellbeing", "Teacher wellbeing score (0-100)"),
    ("pss_sessions_delivered", "school", "simple", "pss_sessions", "", "", "PSS sessions delivered", "PSS sessions delivered this month"),
    ("pss_session_fidelity", "school", "simple", "pss_fidelity", "", "", "PSS fidelity", "Share of PSS steps delivered as designed (0-100)"),
    ("safety_lessons_delivered", "school", "simple", "safety_lessons", "", "", "Safety lessons delivered", "Personal-safety lessons delivered this month"),
    ("safe_environment_score", "school", "simple", "safe_environment", "", "", "Safe environment score", "Safe-environment checklist score (0-100)"),
    ("caregiver_sessions_held", "school", "simple", "caregiver_sessions", "", "", "Caregiver sessions held", "Caregiver sessions held this month"),
    ("caregiver_attendance_rate", "school", "simple", "caregiver_attendance", "", "", "Caregiver attendance", "Share of invited caregivers attending (0-100)"),
    ("shock_intensity", "school", "simple", "shock_intensity", "", "", "Shock intensity", "Severity of shocks affecting the school (0-3)"),
    ("distance_to_school_km", "school", "simple", "distance_km", "", "", "Distance to school", "Mean distance from home to school (km)"),
]

# driver_id, indicator_id, role, report_agg
DRIVER_INDICATORS = [
    ("d_01", "literacy", "outcome", "change_from_baseline"),
    ("d_01", "cpd_sessions_attended", "implementation_quantity", "mean"),
    ("d_01", "teaching_quality_score", "implementation_quality", "mean"),
    ("d_01", "class_size", "context", "mean"),
    ("d_01", "teacher_wellbeing", "context", "mean"),
    ("d_02", "wellbeing", "outcome", "change_from_baseline"),
    ("d_02", "pss_sessions_delivered", "implementation_quantity", "mean"),
    ("d_02", "pss_session_fidelity", "implementation_quality", "mean"),
    ("d_02", "shock_intensity", "context", "mean"),
    ("d_02", "teacher_wellbeing", "context", "mean"),
    ("d_03", "perceived_safety", "outcome", "change_from_baseline"),
    ("d_03", "safety_lessons_delivered", "implementation_quantity", "mean"),
    ("d_03", "safe_environment_score", "implementation_quality", "mean"),
    ("d_03", "shock_intensity", "context", "mean"),
    ("d_03", "distance_to_school_km", "context", "mean"),
    ("d_04", "child_attendance_rate", "outcome", "change_from_baseline"),
    ("d_04", "caregiver_sessions_held", "implementation_quantity", "mean"),
    ("d_04", "caregiver_attendance_rate", "implementation_quality", "mean"),
    ("d_04", "distance_to_school_km", "context", "mean"),
    ("d_04", "class_size", "context", "mean"),
]

DIMENSIONS = [
    ("date_time", "ordinal", "_submission_time", "", "", "", "last", "Submission or assessment date"),
    ("admin0", "categorical", "country", "", "", "", "first", "Country"),
    ("admin1", "categorical", "admin1", "", "", "", "first", "Region / governorate"),
    ("school_id", "categorical", "school_id", "", "", "", "first", "School identifier"),
    ("class_id", "categorical", "class_id", "", "", "", "first", "Class identifier"),
    ("teacher_id", "categorical", "teacher_id", "", "", "", "first", "Teacher identifier"),
    ("child_id", "categorical", "child_id", "", "", "", "first", "Child identifier"),
    ("sex", "categorical", "sex", "male,female", "", "", "first", "Child sex"),
    ("age", "ordinal", "age", "", "", "", "last", "Child age in years"),
    ("age_group", "derived", "age", "", "bin", "0:8:6-8|9:11:9-11|12:14:12-14", "last", "Age band"),
    ("round", "categorical", "round", "baseline,endline", "", "", "first", "Assessment round"),
    ("year_month", "ordinal", "year_month", "", "", "", "last", "Calendar month (YYYY-MM)"),
    ("displacement_status", "categorical", "displacement_status", "host_community,idp,returnee", "", "", "first", "Displacement category"),
    ("disability", "categorical", "disability_status", "disability,no_disability", "", "", "first", "Disability status"),
]


def write_config():
    CONFIG.mkdir(parents=True, exist_ok=True)
    ind_cols = ["id", "level", "type", "agg_type", "columns", "calc_op", "calc_by", "calc_sum",
                "agg_method", "missing_handling", "label", "description", "active",
                "driver_id", "driver_level", "report_agg"]
    di = pd.DataFrame(DRIVER_INDICATORS, columns=["driver_id", "indicator_id", "role", "report_agg"])
    di.insert(0, "id", di["driver_id"] + "__" + di["indicator_id"])

    rows = []
    for ind_id, level, agg_type, cols, op, by, label, desc in INDICATORS:
        links = di[di["indicator_id"] == ind_id]
        rows.append({
            "id": ind_id, "level": level, "type": "numeric", "agg_type": agg_type, "columns": cols,
            "calc_op": op, "calc_by": by, "calc_sum": "", "agg_method": "mean", "missing_handling": "",
            "label": label, "description": desc, "active": True,
            "driver_id": "|".join(links["driver_id"]),
            "driver_level": "|".join(links["role"]),
            "report_agg": links["report_agg"].iloc[0] if len(links) else "",
        })
    pd.DataFrame(rows, columns=ind_cols).to_csv(CONFIG / "indicators.csv", index=False)

    dims = pd.DataFrame(DIMENSIONS, columns=["id", "type", "columns", "values", "operation", "bins", "agg_method", "description"])
    dims["active"] = True
    dims.to_csv(CONFIG / "dimensions.csv", index=False)

    drivers = pd.DataFrame(DRIVERS, columns=["driver_id", "label", "description", "unit_level"])
    drivers.insert(0, "id", drivers["driver_id"])
    drivers.to_csv(CONFIG / "drivers.csv", index=False)
    di.to_csv(CONFIG / "driver_indicators.csv", index=False)


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def clip_round(x, lo, hi, digits=1):
    return np.round(np.clip(x, lo, hi), digits)


def generate_country(name, spec, rng):
    code = spec["code"]
    schools, classes, children = [], [], []
    trait_names = ["cpd", "tq", "pss", "pss_fid", "safety", "safe_env", "cg", "cg_att"]

    for s in range(1, N_SCHOOLS + 1):
        sid = f"{code}-S{s:02d}"
        traits = {t: rng.uniform(-1, 1) for t in trait_names}
        schools.append({
            "school_id": sid, "admin1": spec["admin1"][(s - 1) % 3],
            "shock": int(rng.choice([0, 1, 2, 3], p=[0.3, 0.3, 0.25, 0.15])),
            "distance": round(float(rng.uniform(0.5, 7)), 1),
            **traits,
        })
        for c in range(1, CLASSES_PER_SCHOOL + 1):
            cid = f"{sid}-C{c}"
            tid = f"{sid}-T{c}"
            classes.append({
                "school_id": sid, "class_id": cid, "teacher_id": tid,
                "size": int(rng.integers(25, 56)),
                "tcpd": np.clip(traits["cpd"] + rng.normal(0, 0.3), -1.2, 1.2),
                "ttq": np.clip(traits["tq"] + rng.normal(0, 0.3), -1.2, 1.2),
                "twb": rng.uniform(40, 90),
            })
            for k in range(1, CHILDREN_PER_CLASS + 1):
                children.append({
                    "school_id": sid, "class_id": cid, "teacher_id": tid,
                    "child_id": f"{cid}-K{k:02d}",
                    "sex": rng.choice(["male", "female"]),
                    "age": int(rng.integers(6, 15)),
                    "displacement_status": rng.choice(["host_community", "idp", "returnee"], p=[0.5, 0.35, 0.15]),
                    "disability_status": rng.choice(["no_disability", "disability"], p=[0.9, 0.1]),
                })
    schools = pd.DataFrame(schools).set_index("school_id")
    classes = pd.DataFrame(classes).set_index("class_id")
    children = pd.DataFrame(children)
    n = len(children)

    sch = schools.loc[children["school_id"]].reset_index(drop=True)
    cls = classes.loc[children["class_id"]].reset_index(drop=True)
    base = children.assign(country=name, admin1=sch["admin1"].values)

    # outcome gains depend on school/teacher implementation, so CIOs show a real signal
    ability = rng.normal(0, 1, n)
    lit0 = 40 + 10 * ability + rng.normal(0, 4, n)
    lit_gain = 4 + 6 * cls["tcpd"] + 6 * cls["ttq"] - 0.1 * (cls["size"] - 40) + rng.normal(0, 4, n)
    wb0 = 3 + 0.4 * ability + rng.normal(0, 0.4, n)
    wb_gain = 0.3 + 0.35 * sch["pss"] + 0.35 * sch["pss_fid"] - 0.12 * sch["shock"] + rng.normal(0, 0.3, n)
    sf0 = 2.5 + rng.normal(0, 0.35, n) - 0.1 * sch["shock"]
    sf_gain = 0.15 + 0.3 * sch["safety"] + 0.3 * sch["safe_env"] + rng.normal(0, 0.25, n)

    assess = []
    for rnd, ym, date, lit, wb, sf in [
        ("baseline", "2025-09", "2025-09-15", lit0, wb0, sf0),
        ("endline", "2026-03", "2026-03-15", lit0 + lit_gain, wb0 + wb_gain, sf0 + sf_gain),
    ]:
        d = base.copy()
        d["round"], d["year_month"], d["assessment_date"] = rnd, ym, date
        d["literacy_score"] = clip_round(lit + rng.normal(0, 2, n), 0, 100)
        for item in ["wb_happy", "wb_calm", "wb_hopeful"]:
            d[item] = clip_round(wb + rng.normal(0, 0.4, n), 1, 5, 0)
        d["safety_feeling"] = clip_round(sf + rng.normal(0, 0.2, n), 1, 4, 0)
        assess.append(d)
    child_assessments = pd.concat(assess, ignore_index=True)

    att_p = np.clip(
        0.80 + 0.06 * sch["cg"] + 0.05 * sch["cg_att"] - 0.012 * sch["distance"] - 0.025 * sch["shock"], 0.4, 0.97
    ).values
    monthly = []
    for i, m in enumerate(MONTHS):
        d = base[["country", "school_id", "class_id", "teacher_id", "child_id", "admin1", "sex", "age",
                  "displacement_status", "disability_status"]].copy()
        d["year_month"] = str(m)
        d["days_enrolled"] = 20
        p = np.clip(att_p + 0.01 * i * (0.5 + sch["cg"].values) + rng.normal(0, 0.03, n), 0.2, 1)
        d["days_attended"] = rng.binomial(20, p)
        monthly.append(d)
    child_monthly = pd.concat(monthly, ignore_index=True)

    t_rows = []
    for i, m in enumerate(MONTHS):
        for cid, c in classes.iterrows():
            t_rows.append({
                "country": name, "school_id": c["school_id"], "class_id": cid, "teacher_id": c["teacher_id"],
                "admin1": schools.loc[c["school_id"], "admin1"], "year_month": str(m),
                "cpd_sessions": int(rng.poisson(max(0.2, 1.5 + 1.2 * c["tcpd"]))),
                "teaching_quality": clip_round(60 + 18 * c["ttq"] + 0.8 * i + rng.normal(0, 4), 0, 100),
                "class_size": int(c["size"] + rng.integers(-2, 3)),
                "teacher_wellbeing": clip_round(c["twb"] + rng.normal(0, 5), 0, 100),
            })
    teacher_monthly = pd.DataFrame(t_rows)

    s_rows = []
    for i, m in enumerate(MONTHS):
        for sid, s in schools.iterrows():
            s_rows.append({
                "country": name, "school_id": sid, "admin1": s["admin1"], "year_month": str(m),
                "pss_sessions": int(rng.poisson(max(0.3, 4 + 2.5 * s["pss"]))),
                "pss_fidelity": clip_round(65 + 20 * s["pss_fid"] + rng.normal(0, 4), 0, 100),
                "safety_lessons": int(rng.poisson(max(0.3, 2 + 1.5 * s["safety"]))),
                "safe_environment": clip_round(65 + 20 * s["safe_env"] + rng.normal(0, 4), 0, 100),
                "caregiver_sessions": int(rng.poisson(max(0.2, 1.5 + 1.2 * s["cg"]))),
                "caregiver_attendance": clip_round(55 + 25 * s["cg_att"] + rng.normal(0, 5), 0, 100),
                "shock_intensity": int(np.clip(s["shock"] + rng.choice([-1, 0, 0, 1]), 0, 3)),
                "distance_km": round(float(np.clip(s["distance"] + rng.normal(0, 0.2), 0.3, 9)), 1),
            })
    school_monthly = pd.DataFrame(s_rows)

    return {
        "child_assessments": child_assessments,
        "child_monthly": child_monthly,
        "teacher_monthly": teacher_monthly,
        "school_monthly": school_monthly,
    }


def write_data():
    DATA.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    for name, spec in COUNTRIES.items():
        for table, df in generate_country(name, spec, rng).items():
            df.to_csv(DATA / f"{table}_{name.lower()}.csv", index=False)


# --------------------------------------------------------------------------
# schema.sql
# --------------------------------------------------------------------------
def write_schema():
    dim_types = {"admin0": "text", "admin1": "text", "class_id": "text", "teacher_id": "text",
                 "child_id": "text", "sex": "text", "age": "double precision", "age_group": "text",
                 "round": "text", "year_month": "text", "displacement_status": "text", "disability": "text"}
    body = ["country text", "school_id text", "date_time text"]
    body += [f'"{c}" {t}' for c, t in dim_types.items()]
    body += [f'"{i[0]}" double precision' for i in INDICATORS]

    def table(name, key):
        first = "_uuid text primary key" if key == "uuid" else "id bigint generated always as identity primary key"
        tail = ",\n  constraint combined_school_level_key unique (country, school_id, date_time)" if key == "school" else ""
        return f"create table public.{name} (\n  " + ",\n  ".join([first] + body) + tail + "\n);\n"

    sql = [
        "-- DESTRUCTIVE: drops and recreates the combined tables and clears pipeline outputs.",
        "-- Run in the Supabase SQL editor.",
        "-- Config tables are created/synced with: python -m src.update_config <table> <csv>",
        "",
        "drop table if exists combined_child_level, combined_teacher_level, combined_school_level;",
        "truncate table indicator_values, cio_table, narratives, import_log;",
        "",
        table("combined_child_level", "uuid"),
        table("combined_teacher_level", "uuid"),
        table("combined_school_level", "school"),
        "notify pgrst, 'reload schema';",
    ]
    (ROOT / "schema.sql").write_text("\n".join(sql), encoding="utf-8")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def validate():
    problems = []
    ind = pd.read_csv(CONFIG / "indicators.csv")
    files = {"child": ["child_assessments", "child_monthly"], "teacher": ["teacher_monthly"], "school": ["school_monthly"]}
    for country in COUNTRIES:
        cl = country.lower()
        frames = {t: pd.read_csv(DATA / f"{t}_{cl}.csv") for ts in files.values() for t in ts}
        for _, r in ind.iterrows():
            cols = [c.strip() for c in r["columns"].split(",")]
            found = [t for t in files[r["level"]] if all(c in frames[t].columns for c in cols)
                     and (pd.isna(r["calc_by"]) or r["calc_by"] in frames[t].columns)]
            if not found:
                problems.append(f"{country}: {r['id']} columns {cols} not in any {r['level']} file")
                continue
            vals = frames[found[0]][cols].apply(pd.to_numeric, errors="coerce")
            if vals.isna().all().any():
                problems.append(f"{country}: {r['id']} has an all-null column")
            if (vals.nunique() <= 1).any():
                problems.append(f"{country}: {r['id']} is constant")
        keys = {"child_assessments": ["child_id", "round"], "child_monthly": ["child_id", "year_month"],
                "teacher_monthly": ["class_id", "year_month"], "school_monthly": ["school_id", "year_month"]}
        for t, k in keys.items():
            if frames[t].duplicated(k).any():
                problems.append(f"{country}: {t} not unique on {k}")

    di = pd.read_csv(CONFIG / "driver_indicators.csv")
    for d, g in di.groupby("driver_id"):
        for role in ["outcome", "implementation_quality", "implementation_quantity", "context"]:
            if role not in set(g["role"]):
                problems.append(f"{d} lacks {role}")
    unknown = set(di["indicator_id"]) - set(ind["id"])
    if unknown:
        problems.append(f"driver_indicators reference unknown indicators {unknown}")
    print("VALIDATION:", "OK" if not problems else "PROBLEMS")
    for p in problems:
        print(" -", p)
    return not problems


if __name__ == "__main__":
    write_config()
    write_data()
    write_schema()
    ok = validate()
    for f in sorted(DATA.glob("*.csv")):
        print(f"{f.name}: {sum(1 for _ in open(f)) - 1} rows")
    raise SystemExit(0 if ok else 1)
