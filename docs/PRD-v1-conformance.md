# PRD-v1 conformance audit

Audited: 2026-10-06, working tree of D:\Projects\Aura (uncommitted changes included; migrations 0001-0010).
Suite state: `cd backend && uv run pytest tests -q` -> **490 passed**, 0 failed; `lint-imports` 1 kept / 0 broken; `alembic check` no drift; frontend `npm run build` passes.
Counts (section 1, 128 rows): **DONE 123 / PARTIAL 5 / GAP 0 / DEVIATION 0**.
Status key: DONE = every applicable layer evidenced; PARTIAL = see note; GAP = not implemented; DEVIATION = built differently from the PRD.
Layers: BE = backend file (paths under backend/src/aura); TEST = backend/tests file::name; FE = frontend file or n/a. Constraint/CHECK names live in `data/models/tables.py`.

---

## 1. Requirement matrix

### 1.1 Section 2: gaps claimed fixed

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| G2.1 | Jobs/segments tied to deal; task + handoff model | api/routers/jobs.py; core/services/submit_job.py; run_segment.py | unit/test_run_segment::test_gated_run_ends_segment_and_creates_task_and_handoff; unit/test_submit_job::test_job_on_a_deal_the_submitter_cannot_see_is_not_found | deals/components/AgentActions.tsx; jobs/JobsWorkspace.tsx | DONE |
| G2.2 | Approval gate gains materiality limits | core/policy/gate_policy.py; config.py (`AURA_MATERIALITY_CAP_INR`) | unit/test_gate_materiality::*; unit/test_run_segment::test_materiality_above_the_cap_gates_even_an_ungated_category | n/a | DONE |
| G2.3 | Deals: stage machine, history, parties, guards | see F1-F3 | see F1-F3 | see F1-F3 | DONE |
| G2.4 | MCP deals server reads DB | mcp/servers/deals_server.py | integration/test_deals_server::test_get_deal_status_reads_the_database | n/a | DONE (now attached to the crew, F11.3) |
| G2.5 | dealmaker / analyst / compliance roles | core/domain/enums.py:31-35; core/policy/rbac_policy.py:28-35 | unit/test_rbac_policy::*; integration/test_roles_users::* | features/auth/roles.ts, useCan.ts | DONE |
| G2.6 | Audit hash-chained | core/domain/audit.py; data/repositories/sql.py | integration/test_audit_chain::* | AuditChainStatus.tsx, ActivityFeed.tsx | DONE |
| G2.7 | Model runs persisted | data/run_sink.py; agents/llm/recording.py; agents/crewai/recording_llm.py | integration/test_agents_in_the_loop::test_every_run_is_recorded_and_traceable_to_its_exact_prompt | deals/components/RunsTab.tsx | DONE |
| G2.8 | Migrations instead of create_all | migrations/versions/0001-0010; data/seed.py:111 migrate() | integration/test_migrations*, test_migrations_m3/m4/m5::* (incl. alembic check, full down/up) | n/a | DONE |

### 1.2 Section 3: roles

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| R3.1 | `dealmaker` role exists and is enforced | enums.py:33; rbac_policy.py:30 (TRANSITION_DEAL, RESOLVE_HANDOFF, flags + deal work); seed bhavesh=dealmaker (seed.py:23) | unit/test_rbac_policy::test_every_role_has_a_distinct_set_of_powers; integration/test_roles_users::test_only_a_dealmaker_moves_a_deal | roles.ts, useCan.ts | DONE |
| R3.2 | `analyst` role (documents, diligence, agent jobs) | rbac_policy.py:32 (`_DEAL_WORK`) | integration/test_roles_users::test_an_analyst_does_the_deal_work_but_decides_nothing | roles.ts | DONE |
| R3.3 | `compliance` role | rbac_policy.py:33-34 | integration/test_roles_users::test_compliance_reads_and_signs_off_but_does_not_edit_deal_data | roles.ts | DONE |
| R3.4 | `admin` manages users and reference data | users API (api/routers/users.py; core/services/users.py:22,41), admin has no deal powers (rbac_policy.py:29) | integration/test_roles_users::test_only_admin_manages_users, ::test_the_last_active_admin_cannot_be_demoted_or_deactivated, ::test_admin_has_no_deal_powers | features/admin/components/UsersAdmin.tsx; nav.ts (admin only) | PARTIAL: users fully managed; reference data (stage_guard rows, checklist templates) has no admin API/UI, only seed.py / raw SQL |
| R3.5 | Dealmaker approves gated stage transitions | transition_deal.py:60-73 + rbac_policy.py:38-54 check_transition_actor | unit/test_transition_deal::test_only_a_dealmaker_may_make_an_ordinary_move; unit/test_rbac_policy::test_transition_actor_rule | AdvanceSheet.tsx (role-aware) | DONE |
| R3.6 | Dealmaker approves outbound drafts | rbac_policy.py:67-83 (RESOLVE_HANDOFF = dealmaker; compliance only `policy_required`) | integration/test_handoff_api::test_analyst_and_admin_cannot_resolve, ::test_compliance_resolves_policy_required_handoffs_only; unit/test_handoffs::test_only_a_dealmaker_resolves_a_non_policy_handoff | DecisionsInbox.tsx (whoCanResolve) | DONE |
| R3.7 | Compliance manages deal walls | core/services/walls.py:18,34; routers/deals.py:168,178 | integration/test_walls::test_only_compliance_manages_membership, ::test_compliance_manages_membership_and_it_takes_effect_immediately | deals/components/DealRail.tsx (add/remove members) | DONE |
| R3.8 | Compliance signs off where deal has regulatory flags | deals.regulatory_flags (tables.py:85); core/services/compliance.py:23,38; deal_signoff table; guard T9_compliance_signoff (seed.py:70) | integration/test_compliance::test_t9_waits_for_a_signoff_exactly_when_the_deal_has_flags, ::test_a_flagged_deal_cannot_leave_diligence_without_compliance, ::test_signoff_is_compliance_only_and_listed | DealRail.tsx (flags, sign-off) | DONE |
| R3.9 | Guard override only by named role | transition_deal.py:71-81 (override applies only where `g.override_role == actor_role`); seed guards name dealmaker (T1-T8, T10) or compliance (T9, T11); compliance may move only as an override of its own guards (rbac_policy.py:38-54) | unit/test_transition_deal::test_override_needs_matching_role_and_justification, ::test_compliance_may_move_a_deal_only_by_overriding_its_own_guards, ::test_compliance_cannot_override_when_any_failing_guard_names_another_role, ::test_a_dealmaker_cannot_override_a_compliance_guard; integration/test_guards::test_compliance_guards_are_overridden_by_compliance_not_the_dealmaker | AdvanceSheet.tsx (override_role per guard, compliance override mode) | DONE |
| R3.10 | One firm, one tenant | n/a | n/a | shared/config.ts FIRM_NAME | DONE |

### 1.3 Section 4: goals

| ID | Goal | Evidence | Status / note |
|---|---|---|---|
| GL1 | 12 stages, move only when guards pass | stage_policy.py; transition_deal.py; seed.py:34-83 guards T1-T11 on every forward move (regressions/exits need a reason code) | DONE (integration/test_guards::test_each_forward_move_has_its_guards_and_they_pass_once_satisfied) |
| GL2 | Stage change, guard evaluation, approval, model run reconstructable | history, stage_guard_evaluation.history_id FK (tables.py:168, set by transition_deal.py:101-102), handoff, agent_run, doc_access_log, audit on every mutation | DONE (integration/test_audit_anchor::test_every_mutation_leaves_an_audit_row; unit/test_transition_deal::test_evaluations_are_linked_to_the_history_row_on_success) |
| GL3 | Agents classify/draft, hand decisions to humans in SOSPE format | handoff_policy.py; services/handoffs.py; capabilities classify_document / draft_email / extract_financials (submit_job.py) | DONE (FE launch: AgentActions.tsx; checklist set-up is deterministic on entering DILIGENCE, not agent-driven) |
| GL4 | Nothing leaves the machine | config.py (Ollama localhost); unit/test_telemetry_optout; send_email never executes (agents/crewai/tools.py) | DONE |

### 1.4 Section 5: features

#### F1 Stage machine

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F1.1 | SOSPE stages + 4 terminal states | enums.py:52-68; stage_policy.py; `ck_stage_valid` | unit/test_stage_policy::test_forward_moves_one_stage_only, ::test_terminal_stages_have_no_moves | StageRail.tsx; deals/types.ts | DONE |
| F1.2 | Permitted backward moves with reason code | stage_policy.py | unit/test_stage_policy::test_permitted_regressions, ::test_regression_needs_reason_code; integration/test_deal_api::test_regression_requires_reason_and_is_flagged | AdvanceSheet.tsx | DONE (regression list not checkable against SOSPE §3.2, not in repo) |
| F1.3 | Append-only `deal_stage_history` row per change | transition_deal.py:97; data/triggers.py | integration/test_deal_api::test_history_is_immutable; unit/test_transition_deal::test_passing_guards_advance_and_write_history_and_audit | HistoryTab (tabs.tsx) | DONE |
| F1.4 | Terminal <=> outcome + closed_at (CHECK) | `ck_deal_terminal_consistent` (tables.py:71) | integration/test_deal_api::test_terminal_check_constraint; unit/test_transition_deal::test_terminal_sets_outcome_and_closed_at | DealDetailView.tsx | DONE |
| F1.5 | Cycle time only from history (I6) | core/services/metrics.py:65 stage_dwell (history only); GET /api/metrics | integration/test_metrics::test_stage_dwell_comes_only_from_history_and_covers_ended_stays, ::test_p90_is_nearest_rank_over_many_stays, ::test_regressions_extend_the_stage_they_left_and_count_as_another_stay | features/metrics/components/MetricsView.tsx | DONE |
| F1.A1 | ORIGINATED->MATCHED rejected | stage_policy.py (409) | integration/test_deal_api::test_illegal_jump_and_missing_reason | AdvanceSheet offers allowed_next only | DONE |
| F1.A2 | Regression w/o reason rejected | stage_policy.py (422) | unit/test_stage_policy::test_regression_needs_reason_code | AdvanceSheet.tsx | DONE |
| F1.A3 | History edit/delete fails at DB | triggers in data/triggers.py | integration/test_deal_api::test_history_is_immutable | n/a | DONE |

#### F2 Declarative guards

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F2.1 | Guards are `stage_guard` rows; kind `sql_predicate` | StageGuardRow (tables.py:143, sql_text); repositories/sql_deals.py evaluate | integration/test_deal_api::test_broken_guard_fails_closed | n/a | DONE (no explicit evaluator-kind column; every guard is a SQL predicate) |
| F2.2 | One evaluation row per guard per attempt | transition_deal.py:82 (records pass, fail, override; kept on block) | unit/test_transition_deal::test_blocking_failure_blocks_but_still_records_evaluation; integration/test_unit_of_work::test_a_blocked_guard_keeps_its_evaluation_rows | AdvanceSheet.tsx | DONE (every forward move now has guards) |
| F2.3 | Erroring guard counts as failed | sql_deals.py evaluate (savepoint, fail closed) | integration/test_deal_api::test_broken_guard_fails_closed | n/a | DONE |
| F2.4 | Override only by named role, with justification | transition_deal.py:69-81; `ck_override_justified` (tables.py:162) | unit/test_transition_deal::test_override_needs_matching_role_and_justification; integration/test_deal_api::test_blocked_transition_then_dealmaker_override | AdvanceSheet.tsx | DONE |
| F2.5 | Simplified T1-T12 set from held data | seed.py:34-83: T1-T11, one set per forward move (T9 has two: blockers + compliance sign-off) | integration/test_guards::test_each_forward_move_has_its_guards_and_they_pass_once_satisfied, ::test_t1_needs_a_linked_party_that_has_an_identifier, ::test_t5_needs_both_a_counterparty_and_an_executed_nda, ::test_t6_needs_two_distinct_counterparties | AdvanceSheet GuardRow | DONE (no T12: 11 forward moves; retired T3_has_document / T5_counterparty_on_deal kept inactive, seed.py:86) |
| F2.T2 | T2 signed engagement letter | seed.py:39 (`doc_class='engagement_letter' AND is_executed = 1`) | integration/test_guards::test_executed_documents_only_count_while_marked_executed | DocumentsTab.tsx (executed toggle) | DONE |
| F2.T3 | T3 mandate with >=1 hard criterion | seed.py:42-45 (`c.hardness = 'hard'`) | integration/test_guards::test_t3_wants_a_hard_criterion_not_just_any_mandate | MandateTab.tsx | DONE |
| F2.T9 | T9 zero open blocker items | seed.py:65-69 (checklist must exist; open = open/requested/received/under_review/failed) | integration/test_guards::test_t9_blockers_must_exist_and_none_may_be_open_requested_received_or_failed | tabs.tsx diligence | DONE |
| F2.T11 | T11 every CP satisfied or waived | seed.py:77-82 (>=1 CP must exist) | integration/test_guards::test_t11_needs_a_condition_to_exist_and_all_to_be_cleared | tabs.tsx ConditionsTab | DONE |
| F2.A1 | New guard by inserting a row | guards read per attempt (sql_deals.py list_active) | integration/test_deal_api::test_broken_guard_fails_closed (guard inserted via SQL) | n/a | DONE (see R3.4: no API/UI to manage guards) |
| F2.A2 | Each transition in demo deal has evaluation rows | evaluations linked to history via history_id | integration/test_guards::test_scripted_deal_reaches_closed_with_guard_rows_for_every_move (per-move join history->evaluation) | n/a | DONE |

#### F3 Parties and identifiers

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F3.1 | CIN/PAN/GSTIN/DIN format checks | core/policy/identifier_policy.py + DB CHECK `ck_identifier_format` (tables.py:191, migration 0009) | unit/test_identifier_policy::*; integration/test_identifier_checks::test_a_malformed_identifier_cannot_be_inserted_raw, ::test_the_service_and_the_database_agree_on_every_valid_value | PartiesTab (tabs.tsx) | DONE |
| F3.2 | scheme+value unique | `uq_identifier_scheme_value` (tables.py:189) | integration/test_deal_api::test_parties_validation_and_duplicates | tabs.tsx | DONE |
| F3.3 | deal_party roles | `ck_role_valid`; routers/deals.py | integration/test_deal_api::test_parties_validation_and_duplicates | tabs.tsx | DONE |
| F3.4 | Exact identifier match only | core/services/parties.py | test_parties_validation_and_duplicates | n/a | DONE |
| F3.A1 | Malformed PAN fails; duplicate CIN fails | API 422/409 + DB CHECK/UNIQUE | test_parties_validation_and_duplicates; test_identifier_checks::* | tabs.tsx | DONE |

#### F4 Mandates and criteria (P1)

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F4.1 | mandate + mandate_criteria, hard/soft/preference (SOSPE §6.2) | tables.py:206-233 (side, status; criterion_key, operator eq/in/gte/lte/between/not_in/contains, JSON value, hardness, weight 0-1 required for soft: `ck_soft_needs_weight`, `ck_weight_range`); core/services/mandates.py:41; migration 0010 (data mapping + downgrade) | integration/test_deal_api::test_mandates; integration/test_migrations_m5::test_mandates_take_the_sospe_shape_and_come_back | deals/components/MandateTab.tsx (new shape) | DONE |
| F4.2 | T3 needs >=1 hard criterion | seed.py:42-45 | integration/test_guards::test_t3_wants_a_hard_criterion_not_just_any_mandate | n/a | DONE |

#### F5 Documents

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F5.1 | Local store, sha256, class, version | data/filestore.py; services/documents.py; `doc_version` (tables.py:257) | integration/test_documents::test_same_filename_on_the_same_deal_adds_a_version_row_and_bumps_the_document, ::test_doc_version_primary_key_is_document_and_version | DocumentsTab.tsx (versions) | DONE |
| F5.2 | Every view or download writes doc_access_log | services/documents.py:76 view_document + download -> log_access (sql_deals.py:346) | integration/test_documents::test_metadata_view_and_download_are_logged_but_listing_is_not; integration/test_walls::test_document_download_and_access_log_are_walled | DocumentsTab.tsx:118 ("Downloads are logged") | DONE (listing a deal's documents, metadata only, is deliberately not logged) |
| F5.3 | UPSI => sensitivity 4 (CHECK) | `ck_upsi_sensitivity` (tables.py:240) | integration/test_deal_api::test_upsi_check_constraint | DocumentsTab.tsx | DONE |
| F5.4 | Agent proposes class, human confirms | services/handoffs.py classification apply; document.class_confirmed; PATCH /api/documents/{id} | integration/test_agents_in_the_loop::test_classify_document_arrives_as_a_handoff_and_confirming_sets_the_class; integration/test_documents::test_patch_sets_executed_and_class_and_a_chosen_class_is_confirmed | AgentActions.tsx (classify), DocumentsTab.tsx (class_confirmed shown) | DONE |
| F5.5 | Extraction feeding valuation needs conf >=0.95 or human sign-off | extraction table + `ck_extraction_valuation_gate` (tables.py:271); domain/extraction.py:5 CONFIDENCE_GATE; services/extractions.py:18,51 | integration/test_extractions::test_the_database_refuses_an_unverified_low_confidence_extraction_that_feeds_valuation, ::test_a_doubtful_extraction_raises_a_confidence_handoff_with_verify_and_discard, ::test_verify_endpoint_by_dealmaker_or_analyst | ExtractionsTab.tsx | DONE (no valuation consumer exists yet; gate is the `feeds_valuation` flag) |

#### F6 Diligence checklist

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F6.1 | checklist_template, checklist_item_template, diligence_item; 4 severities | tables.py:300,311,323 (template has layer + version); seed.py:89-105 | integration/test_findings_diligence::test_item_templates_belong_to_a_template_with_a_layer_and_version, ::test_template_rows_are_checked | tabs.tsx diligence | DONE |
| F6.2 | Entering DILIGENCE creates checklist for class | transition_deal.py:109-110; services/diligence.py:14 | unit/test_transition_deal::test_entering_diligence_instantiates_checklist_once; integration/test_findings_diligence::test_entering_diligence_instantiates_items_from_the_deals_templates | tabs.tsx | DONE |
| F6.3 | Satisfied needs evidence; waived needs justification (CHECK) | `ck_satisfied_needs_evidence`, `ck_waived_needs_justification` (tables.py:328-330) | integration/test_findings_diligence::test_satisfied_without_evidence_is_refused_by_the_database, ::test_waived_without_justification_is_refused_by_the_database, ::test_updating_an_item_into_satisfied_or_waived_hits_the_same_checks | tabs.tsx | DONE |

#### F7 Tasks and handoffs

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F7.1 | approvals replaced by task + handoff | migration 0004; approvals code deleted | integration/test_migrations_m3::test_approvals_become_handoffs_and_come_back; integration/test_api::test_the_approvals_api_is_gone | DecisionsInbox.tsx at /decisions (/approvals redirects) | DONE |
| F7.2 | Bot-to-human 422 without decision_required / if_you_do_nothing | handoff_policy.py; services/handoffs.py:61 (422 audited as handoff_rejected) | integration/test_handoff_api::test_bot_to_human_handoff_missing_required_parts_is_422; unit/test_handoffs::test_incomplete_bot_to_human_package_is_rejected | n/a | DONE |
| F7.3 | Human-to-bot needs directive incl. do_not_revisit | handoff_policy.py:87-93 | integration/test_handoff_api::test_human_to_bot_handoff_needs_a_directive_with_do_not_revisit; unit/test_handoffs::test_resolve_needs_a_complete_directive | DecisionsInbox.tsx (directive incl. do_not_revisit) | DONE (no FE to create a standalone human-to-bot handoff; X14) |
| F7.3b | do_not_revisit honoured | run_segment.py:37-42 (prior directive on same deal + task type), :123 audits `handoff_skipped_per_directive` | integration/test_do_not_revisit::*; unit/test_run_segment_extras::test_do_not_revisit_skips_the_new_handoff_and_applies_the_earlier_approval, ::test_a_directive_on_another_deal_does_not_skip | activity present.ts | DONE |
| F7.4 | gate_policy single decision point + materiality cap | gate_policy.py; run_segment.py; agents/crewai/tools.py (tool calls gated before running) | unit/test_gate_materiality::*; unit/test_crew_tools::test_an_ungated_tool_above_the_materiality_cap_is_gated_too; integration/test_handoff_api::test_materiality_above_the_cap_gates_and_is_flagged | DecisionsInbox.tsx | DONE |
| F7.A1 | Handoff w/o if_you_do_nothing -> 422 | as F7.2 | as F7.2 | n/a | DONE |
| F7.A2 | Outbound email always a handoff, never executed | stub_orchestrator.py:138; crewai/orchestrator.py:218 (_draft_email: Drafter output = body, reviewer critique = review_notes); tools.py send_email body unreachable; services/outbound.py | integration/test_agents_in_the_loop::test_email_draft_is_always_a_handoff_and_is_never_sent; unit/test_crew_tools::test_the_real_send_email_body_is_unreachable_from_the_crew, ::test_a_draft_email_job_never_sends_even_if_the_agent_tries; unit/test_crew_orchestrator::test_the_email_draft_is_the_drafters_output_not_the_reviewers_critique; integration/test_metrics::test_no_email_flow_ever_executes_an_outbound_action | DecisionsInbox.tsx | DONE (cosmetic: resumed plain-brief segments still set `context.sent = True`, crewai/orchestrator.py:136, stub_orchestrator.py:70, though nothing is sent) |

#### F8 Model run lineage

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F8.1 | agent_run per Ollama call with full lineage | agents/llm/recording.py; crewai/recording_llm.py | unit/test_agent_runs::*; unit/test_crew_recording::test_instrumented_llm_records_every_call | RunsTab.tsx | DONE (live crew path covered with fake LLM in tests) |
| F8.2 | cost 0, column exists | recording.py (cost_inr=0.0) | integration/test_agents_in_the_loop::test_every_run_is_recorded_and_traceable_to_its_exact_prompt | n/a | DONE |
| F8.3 | Unrecorded run -> output not used | recording.py; run_sink.py | integration/test_agents_in_the_loop::test_if_the_run_cannot_be_recorded_its_output_is_not_used; unit/test_crew_recording::test_instrumented_llm_raises_instead_of_returning_unrecorded_output | n/a | DONE |
| F8.A | 100% of sampled runs traceable to prompt | GET /api/agent-runs/{id} (routers/agent_runs.py) | test_every_run_is_recorded_and_traceable_to_its_exact_prompt; integration/test_metrics::test_untraceable_runs_lower_the_traceability_percentage | RunsTab.tsx (getAgentRun drill-down: exact prompt + output) | DONE |

#### F9 Hash-chained audit

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F9.1 | prev_hash/row_hash chain | audit.py; sql.py; AuditResponse exposes hashes + deal_id (api/schemas/dto.py:37-46) | integration/test_audit_chain::test_chain_links_from_genesis_and_verifies; integration/test_audit_anchor::test_activity_exposes_the_hash_chain_and_deal_id | ActivityFeed.tsx (row_hash shown) | DONE |
| F9.2 | `verify-audit` reports first broken link | data/verify_audit.py (`python -m aura.data.verify_audit`); GET /api/audit/verify | integration/test_audit_chain::test_verify_detects_tampering_at_the_edited_row, ::test_verify_detects_deleted_row | AuditChainStatus.tsx | DONE (module, not a console script) |
| F9.3 | Local anchor file (WORM deferred) | data/verify_audit.py:82 write_anchor; backend/data/audit_anchor.json, per-DB path; refreshed by API start-up, worker, verify | integration/test_audit_anchor::test_tail_deletion_is_caught_by_the_anchor_though_the_chain_still_verifies, ::test_deleting_everything_is_caught_too, ::test_default_anchor_path_is_per_database, ::test_verify_endpoint_shape_and_anchor_detection | AuditChainStatus.tsx | DONE |
| F9.A | Hand edit fails verify at that row | verify_audit.py | integration/test_audit_chain::test_verify_detects_tampering_at_the_edited_row; integration/test_audit_anchor::test_editing_a_row_breaks_the_chain_at_that_row | AuditChainStatus.tsx | DONE |

#### F10 Deal walls (P1)

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F10.1 | wall + wall_member, one per deal | tables.py:443,452; create_deal adds creator + every active compliance user | integration/test_walls::test_creating_a_deal_creates_its_wall_with_the_creator_and_compliance_as_members; integration/test_migrations_m3::test_existing_deals_get_a_wall_with_their_owner | DealRail.tsx members | DONE |
| F10.2 | Deal/document reads wall-checked in repository layer | data/walls.py; per-viewer repos (api/deps.py); WS events wall-filtered (api/ws/hub.py) | integration/test_walls::test_non_member_gets_404_on_every_deal_scoped_route, ::test_no_role_is_exempt_from_a_wall, ::test_handoffs_agent_runs_jobs_and_activity_are_filtered; integration/test_events::test_a_deal_event_reaches_only_users_on_that_deals_wall, ::test_if_the_wall_cannot_be_read_the_event_is_dropped_not_broadcast | DealDetailView.tsx (404 state); DealRail.tsx (member UI) | DONE |

#### F11 MCP deals server

| ID | Requirement | BE | TEST | FE | Status / note |
|---|---|---|---|---|---|
| F11.1 | Replace `_DEALS` with repository reads | mcp/servers/deals_server.py | integration/test_deals_server::test_get_deal_status_reads_the_database, ::test_list_deals_returns_all | n/a | DONE |
| F11.2 | Reads apply wall check | mcp/identity.py; deals_server.py | integration/test_deals_server::test_a_non_member_sees_nothing_through_any_tool, ::test_with_no_acting_user_nothing_is_visible | n/a | DONE |
| F11.3 | Agents see real deals and stages | agents/crewai/tools.py:73-87 (deals_server tools attached, each call through gate_policy, run as the submitting user); agents/factory.py:10 | unit/test_orchestrator_factory::test_the_real_crew_gets_the_deals_mcp_tools_behind_the_gate; unit/test_crew_tools::test_the_real_deals_server_tools_are_the_ones_attached_by_default, ::test_send_emails_body_never_runs_and_the_attempt_is_recorded_instead, ::test_the_orchestrator_hands_the_acting_user_to_the_tools | n/a | DONE |

### 1.5 Section 6: constraints

| ID | SOSPE ref | BE / TEST | FE | Status |
|---|---|---|---|---|
| C4 | Replayable audit | F9 + F9.3 anchor + F1.3 + F2.2 (evaluations linked to history); test_audit_anchor::test_every_mutation_leaves_an_audit_row | AuditChainStatus, ActivityFeed | DONE |
| C6 | Model lineage | see F8 | RunsTab.tsx | DONE |
| C7 | Statutory identifiers: format + uniqueness, no live check | F3.1 (service + DB CHECK), F3.2 | PartiesTab | DONE |
| C1/C3 | Walls, application layer | F10 (repository + WS filtering) | DealRail.tsx | DONE (as scoped by PRD: app layer; RLS needs Postgres, D1) |
| C2 | DPDP: data stays local | config.py; no cloud calls | n/a | DONE (consent/erasure deferred per PRD) |
| C5 | Outreach: v1 sends nothing | F7.A2; services/outbound.py; metrics outbound_executed | MetricsView.tsx | DONE |
| I5 | Autonomy capped by materiality, deterministic | gate_policy.py; unit/test_gate_materiality::test_recommendation_is_policy_not_model | n/a | DONE |
| I6 | Cycle time from history only | F1.5 | MetricsView.tsx | DONE |
| I7 | Handoff schema enforced at API | F7.2 | n/a | DONE |
| CL | Local-only, no cloud model/keys | unit/test_telemetry_optout; FE has no external URLs | n/a | DONE (dev JWT default config.py:15 and seed passwords remain; see L6) |

### 1.6 Section 8: data model

New tables.

| ID | Table | Evidence | Status |
|---|---|---|---|
| DM.party | party | 0002/0003 | DONE |
| DM.party_identifier | party_identifier | 0002 UNIQUE; 0009 `ck_identifier_format` | DONE |
| DM.deal_party | deal_party | 0002 | DONE |
| DM.mandate | mandate | 0002; 0010 side + status | DONE |
| DM.mandate_criteria | mandate_criteria | 0002; 0010 SOSPE §6.2 shape | DONE |
| DM.deal_stage_history | deal_stage_history | 0002 + append-only triggers | DONE |
| DM.stage_guard | stage_guard | 0002 (+description 0003) | DONE |
| DM.stage_guard_evaluation | stage_guard_evaluation | 0002; 0008 history_id FK | DONE |
| DM.document | document | 0002/0003; 0007 current_version, is_executed | DONE |
| DM.doc_version | doc_version | 0007 (PK document_id+version) | DONE |
| DM.doc_access_log | doc_access_log | 0002 + append-only triggers | DONE |
| DM.checklist_template | checklist_template | 0009 (layer, version) | DONE |
| DM.checklist_item_template | checklist_item_template | 0002; 0009 grouped under templates | DONE |
| DM.diligence_item | diligence_item | 0002 | DONE |
| DM.finding | finding | 0009; `ck_finding_impact_required`; GET/POST /api/deals/{id}/findings; Findings.tsx | DONE |
| DM.condition_precedent | condition_precedent | 0002 | DONE |
| DM.task | task | 0004 | DONE |
| DM.handoff | handoff | 0004 | DONE |
| DM.agent_run | agent_run | 0005 | DONE |
| DM.wall | wall | 0005 | DONE |
| DM.wall_member | wall_member | 0005 | DONE |

Changed tables and migrations.

| ID | Item | Evidence | Status |
|---|---|---|---|
| DM.deals | transaction_class, outcome, opened_at, closed_at; stage limited | 0002 CHECKs (+ regulatory_flags 0008) | DONE |
| DM.audit_entries | prev_hash, row_hash (+ deal_id) | 0002 (backfilled chain) | DONE |
| DM.approvals | replaced by handoff | 0004, reversible | DONE |
| DM.sqlite | SQLite equivalents for Postgres features | JSON columns, json_array_length in guards/CHECKs | DONE |
| DM.alembic | Alembic prerequisite | backend/alembic.ini; migrations 0001-0010, each with downgrade; seed.py migrate() on start | DONE |

### 1.7 Section 9: open decisions

| ID | Decision | Evidence | Status |
|---|---|---|---|
| D1 | Database | PRD §9: decided 2026-10-06, SQLite for v1, walls in repository layer | DONE |
| D2 | Primary keys | PRD §9: decided 2026-10-06, integer keys for v1 | DONE |
| D3 | Map stage names once in migration | 0002 maps legacy free-text stages to ORIGINATED | DONE (lossy by design) |
| D4 | Keep qwen3.5:4b | config.py | DONE |
| D5 | First real deal chosen | dry run done on demo deal (E2E Kaveri Textiles, see E2E run section); real client deal pending business owner | PARTIAL |

### 1.8 Section 10: milestone exit tests

| ID | Exit test | Evidence | Status |
|---|---|---|---|
| M0 | Upgrade and downgrade on a copy of aura.db; D1/D2 settled | test_migrations::*, test_migrations_m3::test_full_downgrade_to_baseline_and_back, test_migrations_m4::*, test_migrations_m5::test_mandates_take_the_sospe_shape_and_come_back; E2E run: the real backend/aura.db was upgraded in place 0005 -> 0010 at API start; a copy of it was downgraded to 0001 and upgraded back to 0010 (`alembic current` 0001 then 0010, `verify_audit` OK, 3 deals / 66 audit rows intact); D1/D2 decided in PRD | DONE |
| M1 | Scripted deal reaches CLOSED with guard rows for every move; verify passes, then fails after hand edit | integration/test_guards::test_scripted_deal_reaches_closed_with_guard_rows_for_every_move (per-move evaluations, verify ok); integration/test_audit_chain::test_verify_detects_tampering_at_the_edited_row | DONE (pass and fail-after-edit are two tests) |
| M2 | T9 blocks while blocker open, passes once satisfied with evidence | integration/test_guards::test_t9_blockers_must_exist_and_none_may_be_open_requested_received_or_failed; test_scripted_deal_reaches_closed_with_guard_rows_for_every_move | DONE |
| M3 | Job proposes doc class and draft email; valid handoffs; agent_run traces each | integration/test_agents_in_the_loop::* (stub), unit/test_crew_orchestrator::test_the_email_draft_is_the_drafters_output_not_the_reviewers_critique; LIVE in the E2E run (section 4): CrewAI on qwen3.5:4b classified an NDA (0.98) and drafted a lender email, both arrived as valid handoffs, agent_run rows 1-7 carry the exact prompts | DONE |
| M4 | One real deal from D5 end to end | dry run done on demo deal (E2E Kaveri Textiles, see E2E run section); real client deal pending business owner | PARTIAL |

### 1.9 Section 11: success metrics

| ID | Metric | Measured from | Status / note |
|---|---|---|---|
| SM1 | 100% transitions with a guard evaluation | GET /api/metrics `guarded_forward_transitions_pct` (history JOIN evaluations via history_id; forward moves only); integration/test_metrics::* | PARTIAL: mechanism done and the E2E deal is 13/13 guarded forward moves; the live database reads 92.9% because demo deal D-001 moved ORIGINATED -> QUALIFIED (history #3) under an earlier build before T1 existed. The metric reports that honestly; it was not edited away |
| SM2 | 100% runs traceable | `runs_traceable_pct` | DONE (test_metrics::test_untraceable_runs_lower_the_traceability_percentage) |
| SM3 | Audit chain 100% pass | verify_audit, GET /api/audit/verify, `audit_chain_ok` | DONE |
| SM4 | 0 incomplete handoffs reached a human | `handoff_rejections_422` from `handoff_rejected` audit rows | DONE (test_audit_anchor::test_a_422_handoff_rejection_is_audited_and_survives_the_rollback; test_metrics::test_handoff_rejections_and_outbound_executions_are_counted_from_the_audit) |
| SM5 | 0 outbound executed without approval | `outbound_executed` count (services/outbound.py) | DONE (test_metrics::test_no_email_flow_ever_executes_an_outbound_action) |
| SM6 | >=1 real deal end to end | `deals_closed_end_to_end`; M4 | PARTIAL: dry run done on demo deal (E2E Kaveri Textiles, see E2E run section); real client deal pending business owner |

---

## 2. Frontend-backend contract mismatches

Re-checked against the current tree. Frontend base: frontend/shared/api/client.ts; backend routers: backend/src/aura/api/routers/*.

| # | Was | Status / evidence |
|---|---|---|
| X1 | Blank next_checkpoint sent -> 422 | FIXED: DecisionsInbox.tsx:295-296 blocks submit until condition and escalate_if are set; :309 sends trimmed values |
| X2 | `useApi` pages ignored the socket | FIXED: shared/lib/useApi.ts:106-133 (`live` filter -> debounced refetch; fallback polling while socket down); inbox, dashboard, deals, every deal tab, sidebar badge pass `live` |
| X3 | WS EventType drift | FIXED: shared/api/ws.ts:4-11 matches backend events incl. `entity_changed`; ENTITY_KINDS mirrors core/policy/entity_policy.py |
| X4 | Dashboard funnel/ended counts | FIXED: core/services/dashboard.py counts every deal in deals_by_stage, adds closed_deals/ended_deals; DashboardOverview.tsx:107-110 reads them |
| X5 | Rejected resolutions shown as success; missing verbs | FIXED: activity/present.ts:113 tones by `payload.approved`; covers all 31 audited actions (escalated :117, skipped-per-directive :119); integration/test_events::test_every_audited_action_maps_to_a_known_kind_or_none |
| X6 | Hashes/deal_id not exposed | FIXED: api/schemas/dto.py:40,45-46; activity/types.ts; ActivityFeed.tsx:73 |
| X7 | Job statuses/fields drift | FIXED: jobs/types.ts matches JobResponse (dto.py:27-34, created_by); JobsWorkspace.tsx:151. Timeline still rebuilt from activity (no segments endpoint), by design |
| X8 | No job-submit UI | FIXED: deals/components/AgentActions.tsx -> jobs/api.ts runCapability (classify_document, draft_email, extract_financials) |
| X9 | DealDocument missing fields | FIXED: deals/types.ts:83-99 matches DocumentOut (schemas/deals.py:125-138) |
| X10 | "Every view is logged" copy | FIXED: DocumentsTab.tsx:118 "Downloads are logged with your name" |
| X11 | Override offered to everyone, no override_role | FIXED: EvaluationOut has override_role (schemas/deals.py:59); AdvanceSheet.tsx:23-31,115-139 (role-aware; compliance override mode only for compliance-owned failing blocking guards; warnings never need override) |
| X12 | Invented "partner" role, no gating | FIXED: offline DEMO_USER removed; features/auth/roles.ts + useCan.ts mirror rbac_policy |
| X13 | Handoff type incomplete; resolved unused | FIXED: handoffs/api.ts Handoff has job_id, task_type, direction, directive, status incl. escalated; DecisionsInbox.tsx:607 uses listResolvedHandoffs |
| X14 | No FE for members, mandates, POST /api/handoffs | PARTIAL / open (Info): members (DealRail.tsx) and mandates (MandateTab.tsx) FIXED; POST /api/handoffs (creating a standalone human-to-bot handoff) still has no FE caller |
| X15 | Upload 401 / download message | FIXED: deals/api.ts upload uses errorForStatus (401 -> auth-expired); client.ts apiDownload passes server message, wall-specific 404 copy |

---

## 3. Hardcoded / mock leftovers

| # | Was | Status / evidence |
|---|---|---|
| L1 | Hardcoded firm names | FIXED: shared/config.ts:6 FIRM_NAME from NEXT_PUBLIC_FIRM_NAME (default "Aura") used by layout, login, sidebar |
| L2 | Static fake deal card on login | FIXED: login/page.tsx shows an abstract skeleton (stage rail, guard dots, hash chain), no deal data |
| L3 | activity/sample.ts fixtures | FIXED: file removed; offline state shows "can't reach the server" |
| L4 | jobs/sample.ts fixtures | FIXED: file removed |
| L5 | Offline demo session (bhavesh/admin123 client-side) | FIXED: removed from features/auth/hooks.tsx |
| L6 | Seed accounts / dev JWT secret / demo deals | OPEN (documented): seed.py:23-24 users with dev passwords, config.py:15 `dev-secret-change-me`, demo deals D-001/D-002 (seed.py:107); RUNNING.md §8 says change before shared use |
| L7 | /approvals route name | FIXED: app/(portal)/approvals/page.tsx redirects to /decisions; nav.ts uses /decisions (chord letter still `g a`) |
| L8 | Misleading "Polling" pill | FIXED: TopBar.tsx:23-30 pill driven by `connection` (Live / Reconnecting / Offline) |
| L9 | Offline "sample data" banner | FIXED: no sample-data copy remains |
| L10 | TODO / FIXME / lorem | none found in frontend source |

---

## 4. E2E run (real UI, live Ollama)

Run 2026-10-06 against the real stack: backend `uv run uvicorn aura.api.main:app --port 8000` on backend/aura.db (migrated 0005 -> 0010 on start; log line `Orchestrator: CrewAI on http://localhost:11434`), the existing `next dev` on :3000, local Ollama `qwen3.5:4b`. A Playwright script drove the real UI (no fixtures, no mocks), logging in as the role each step needs. Screenshots: `C:\Users\ashis\AppData\Local\Temp\claude\d--Projects-Aura\635430c1-8e67-4412-a633-fbe57b353c8a\scratchpad\e2e\shots\` (index in INDEX.txt).

Deal: **E2E Kaveri Textiles — ₹40 Cr working capital** (E2E-KAV-040, DEBT, deal id 3).

| # | Step | Who | Result | Screenshots |
|---|---|---|---|---|
| 1 | Create the DEBT deal | bhavesh | PASS | 01-03 |
| 2 | Attempt ORIGINATED -> QUALIFIED first: T1 fails, move disabled | bhavesh | PASS (blocked) | 04 |
| 3 | Party Kaveri Textiles Ltd (CIN U17110TZ2010PLC012345, PAN AAACK1234F), issuer -> QUALIFIED (T1) | bhavesh | PASS | 05-06 |
| 4 | Engagement letter uploaded + marked executed -> MANDATED (T2) | bhavesh | PASS | 07-08 |
| 5 | Mandate (side raise; hard `ticket_size_inr between [3.5e8, 4.5e8]`; soft `investor_type in [psu_bank, private_bank]` w 0.6) -> PREPARED (T3) | bhavesh | PASS | 09-11 |
| 6 | Audited financials -> MARKETED (T4) | bhavesh | PASS | 12 |
| 7 | Lender Bank of Baroda (PAN); NDA uploaded under the wrong class; **Classify** and **Draft email** queued from the UI | bhavesh | PASS | 13-15 |
| 8 | Compliance adds asha to the wall; compliance's Advance sheet offers only overrides (none possible here) | priya | PASS | 16-17 |
| 9 | Classify handoff in Decisions, resolved "Confirm nda" with a full directive; class becomes nda, class_confirmed true | bhavesh | PASS | 18-21 |
| 10 | NDA marked executed -> MATCHED (T5) | bhavesh | PASS | 22 |
| 11 | Draft-email handoff (draft body + reviewer notes shown), approved; job completes, nothing sent (`outbound_executed` 0) | bhavesh | PASS | 23-26 |
| 12 | Second lender HDFC Bank (CIN) -> BID_AUCTION (T6); valuation report -> NEGOTIATION (T7); executed term sheet -> DILIGENCE (T8), checklist instantiated (7 items) | bhavesh | PASS | 27-31 |
| 13 | Regression DILIGENCE -> NEGOTIATION with reason `price_renegotiation`, then forward to DILIGENCE again | bhavesh | PASS | 32-35 |
| 14 | Evidence uploaded; both blockers and one material item satisfied with evidence; finding (adjustment, ₹1.8 Cr, affects valuation) raised | asha | PASS | 36-38 |
| 15 | Analyst cannot advance: button disabled, tooltip "Only dealmakers can move a deal between stages." | asha | PASS | 39 |
| 16 | Regulatory flag RBI_LARGE_EXPOSURE set; DOCUMENTATION blocked by T9_compliance_signoff | bhavesh | PASS (blocked) | 40-41 |
| 17 | Compliance sign-off with note | priya | PASS | 42-43 |
| 18 | -> DOCUMENTATION (T9 both pass); executed facility agreement (SPA) -> CONDITIONS_PRECEDENT (T10) | bhavesh | PASS | 44-45 |
| 19 | CLOSED blocked with no CPs (T11); 3 CPs added, 2 satisfied, 1 waived with justification -> **CLOSED** (closed_won) | bhavesh | PASS | 46-51 |
| 20 | Agent runs tab and run drawer show the exact system + user prompt (classifier, drafter); Agent jobs both complete | bhavesh | PASS | 52-55 |
| 21 | Admin sees Users; deal list empty and the deal URL is "not found" (walls bind admin) | admin | PASS | 56-58 |
| 22 | Compliance removes asha from the wall; asha gets "Deal not found" and the deal leaves her list | priya, asha | PASS | 59-61 |
| 23 | Activity: chain verified, anchor matches #66; Metrics | bhavesh | PASS | 62-63 |
| 24 | Dark theme: closed deal, advance sheet with failing guard, resolved decision, metrics | bhavesh | PASS | 64-67 |

After CLOSED: `GET /api/audit/verify` -> `{"ok": true, "broken_at": null, "anchor": {"head_id": 66, "ok": true}}`. `GET /api/metrics` success -> `guarded_forward_transitions_pct 92.9` (E2E deal 13/13; the shortfall is D-001's pre-T1 move, see SM1), `runs_traceable_pct 100`, `audit_chain_ok true`, `handoff_rejections_422 0`, `outbound_executed 0`, `deals_closed_end_to_end 1`.

Live agents (CPU inference): classify 31 s (one Document Classifier call, proposed nda at 0.98 with a correct rationale). Draft email ~3 min 10 s over 6 calls (4 researcher tool turns 1-6 s, drafter 14 s, reviewer 158 s). Bug found and fixed during the run: the email handoff carried the Reviewer's critique as the email body; the body is now the Drafter's task output, with the critique as `review_notes` (orchestrator.py `task_texts`, `split_subject`).

D5 / M4: dry run done on demo deal (E2E Kaveri Textiles); real client deal pending business owner.



## 5. Phase 3: deal intake (auto-filled new deals), 2026-10-13

Scope: PRD F1 (deal creation) gains a document-first path. Creating a deal by uploading its pack, extraction of identity, transaction, parties, financials, terms, regulatory flags, the class profile and mandate criteria, with a human review (confidence, citations, conflicts) before `create_deal` runs. The deal still enters at ORIGINATED through the same service, guards, wall and audit; nothing about the stage machine changed.

| Requirement | Where | Status |
|---|---|---|
| Draft is private until confirmed | RLS `0004_deal_intake` (`aura_viewer_intake_ids()` on document, doc_chunk, index_job, agent_run; deal_intake policy unchanged) + repository filter | Done; `test_a_draft_is_private_to_its_creator` |
| Staged files reuse the index pipeline, chunks re-pointed on confirm | `document.intake_id`, `SqlIntakeRepository.move_to_deal` | Done; same chunk rows (35 for 6 files in the live run) now carry the deal id |
| Extraction never in a request; retries, dead letter, tracing | `worker/intake.py`, `intake.extract` span | Done; deterministic fallback after the last model attempt |
| Model runs recorded, not autonomy-counted | `agent_run.archetype = intake_extractor`, `intake_id` | Done (7 runs in the live intake, re-pointed to the deal) |
| Field validation, ₹ normalisation, conflicts, 0.85 / 0.95 rules | `core/services/intake_fields.py`, `intake_extraction.py` | Done; unit tests |
| Confirm → deal + parties + identifiers + mandate + profile + documents + flags, one unit of work | `core/services/intake.py: confirm_intake` | Done; 409 twice, 422 with `field_errors` |
| Override-rate metric | `GET /api/metrics → evaluation.intake` | Done (live: 1 of 38 auto-filled fields changed) |
| Eval | `python -m aura.evals.run --capability intake` | Done (see RUNNING.md) |

Live run (real UI at `/deals/new`, bhavesh, live `qwen3.5:4b` on CPU, Docling): six Kaveri files (audited financials PDF, NCD term sheet PDF, scanned borrowings schedule PDF, IM DOCX, model XLSX, teaser PPTX) uploaded at 17:10:08; all six indexed by 17:11:40; extraction 209 s (identity, transaction, parties, terms, profile and mandate groups asked; financials skipped because the table grids already gave FY24 revenue ₹412.38 Cr, EBITDA ₹68.15 Cr, PAT ₹31.93 Cr and net debt ₹96.40 Cr at 0.99 across three documents); review ready at 17:15:12 (about 5 minutes from upload). CIN U29253MH2011PTC215478 and PAN AAFCK4821M were found by regex with page citations; the citation pane opened the teaser slide with the revenue row highlighted. One field was corrected by hand (the model gave incorporation date 2011-01-01 from "incorporated in 2011"; it was cleared), eight low-confidence fields were accepted, and confirming created AUR-0002 "Project Kaveri" (DEBT, ORIGINATED) with the issuer party (CIN + PAN), the SEBI flag, a draft mandate with criteria, a 12-field DEBT profile and the six documents already indexed. No conflict arose in this pack, so none was resolved in the UI; conflict resolution is covered by the integration test and the eval's conflict probe.

Bugs found and fixed during the run: the first confirm failed with 422 because a model-suggested criterion (`minimum_rating gte "A-"`) broke the mandate rules (now normalised: a word under gte/lte becomes `eq`; model criteria start unticked; derived criteria come first); the 4B model looped while listing party types under prompt v1 (`intake.parties@v2`, with enum-constrained structured output); free-text fields from two documents raised paraphrase "conflicts" (texts now agree when the shorter wording is contained in the longer); queued files showed a "Reading" spinner; the confirm summary listed no parties (the company is now shown) and rounded ₹412.38 Cr to ₹412 Cr. Screenshots: `scratchpad/intake/shots/01..16`. The Playwright session could not deliver keyboard events to the page, so the `c` shortcut was verified by dispatching the key event in the page.
