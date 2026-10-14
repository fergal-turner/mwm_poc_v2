-- Run in the Supabase SQL editor, then: notify pgrst, 'reload schema';

alter table combined_teacher_level
  add column if not exists country text;

alter table combined_school_level
  add column if not exists country text,
  add column if not exists aep_overage_enrolment double precision,
  add column if not exists aser_literacy double precision,
  add column if not exists aser_numeracy double precision,
  add column if not exists caregiver_practice_improved double precision,
  add column if not exists certified_or_transitioned double precision,
  add column if not exists check_for_understanding double precision,
  add column if not exists child_attendance_rate double precision,
  add column if not exists child_home_support_improved double precision,
  add column if not exists chronic_absence double precision,
  add column if not exists class_management_time double precision,
  add column if not exists class_size double precision,
  add column if not exists classroom_pss_wellbeing_improved double precision,
  add column if not exists cognitive_challenge double precision,
  add column if not exists cpd_events_attended double precision,
  add column if not exists differentiation double precision,
  add column if not exists disability_inclusive_practice double precision,
  add column if not exists disruption_level double precision,
  add column if not exists facilitation_time double precision,
  add column if not exists gender_responsiveness double precision,
  add column if not exists haldo_accuracy double precision,
  add column if not exists haldo_comprehension double precision,
  add column if not exists haldo_empathy double precision,
  add column if not exists haldo_expressive_language double precision,
  add column if not exists haldo_letter_identification double precision,
  add column if not exists haldo_literacy double precision,
  add column if not exists haldo_numeracy double precision,
  add column if not exists haldo_sel double precision,
  add column if not exists haldo_self_concept double precision,
  add column if not exists inclusive_practice_index double precision,
  add column if not exists inclusive_training_completed double precision,
  add column if not exists learning_improved double precision,
  add column if not exists learning_resources double precision,
  add column if not exists lesson_preparedness double precision,
  add column if not exists literacy_practice double precision,
  add column if not exists mhpss_participation double precision,
  add column if not exists numeracy_practice double precision,
  add column if not exists off_task_behaviour double precision,
  add column if not exists perceived_safety double precision,
  add column if not exists play_wellbeing_improved double precision,
  add column if not exists positive_discipline double precision,
  add column if not exists positive_feedback double precision,
  add column if not exists programme_completed double precision,
  add column if not exists pss_facilitator_training_days double precision,
  add column if not exists pss_play_participation double precision,
  add column if not exists retained_in_programme double precision,
  add column if not exists rtl_use double precision,
  add column if not exists safe_environment double precision,
  add column if not exists sel_practice double precision,
  add column if not exists student_participation double precision,
  add column if not exists student_teacher_ratio double precision,
  add column if not exists teacher_attendance_rate double precision,
  add column if not exists teacher_inclusion_knowledge double precision,
  add column if not exists teacher_stress_burnout double precision,
  add column if not exists teacher_wellbeing double precision,
  add column if not exists teaching_practice_index double precision,
  add column if not exists time_on_task double precision,
  add column if not exists unsafe_situation_knowledge double precision,
  add column if not exists wellbeing_improved double precision,
  add column if not exists wellbeing_score double precision;

-- school rows are keyed by school/month, not _uuid, so the school table needs this key for upserts
alter table combined_school_level
  add constraint combined_school_level_key unique (country, school_id, date_time);

-- school -> school_id for consistency
alter table indicator_values rename column school to school_id;

-- Everything is read/written via the API, so use plain numeric/text types.
-- Boolean indicator columns -> numeric (aggregates are 0-1 means, e.g. "0.0")
alter table combined_school_level
  alter column school_management_committee_active type double precision using school_management_committee_active::int,
  alter column referral_mechanism_functioning type double precision using referral_mechanism_functioning::int,
  alter column pss_quality_standard type double precision using pss_quality_standard::int,
  alter column code_of_conduct_functioning type double precision using code_of_conduct_functioning::int,
  alter column play_quality_standard type double precision using play_quality_standard::int,
  alter column pta_active type double precision using pta_active::int,
  alter column safeguarding_policy type double precision using safeguarding_policy::int;
alter table combined_teacher_level
  alter column inclusive_training_completed type double precision using inclusive_training_completed::int;

-- date_time holds period strings like '2025-09' (child table already stores text)
alter table combined_school_level  alter column date_time type text using date_time::text;
alter table combined_teacher_level alter column date_time type text using date_time::text;

-- grade may arrive as 3.0
alter table combined_child_level alter column grade type double precision;
