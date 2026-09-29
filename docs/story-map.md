# Story map: acceptance criteria to tests

IDs follow the final proposal (September 27, 2026). Run everything with
`python -m unittest discover -s tests -t . -v`.

| Criterion | Test |
| --- | --- |
| US-01-AC1 valid profile saved, classified, used for sizing | `test_profile.ProfileTest.test_us01_ac1_valid_profile_saved_and_classified`, `test_scan.ProposalTest.test_us01_ac1_proposal_respects_the_profile` |
| US-01-AC2 invalid or missing values rejected, previous profile kept | `test_profile.ProfileTest.test_us01_ac2_invalid_or_missing_values_rejected`, `test_us01_ac2_previous_profile_stays_in_use`, `test_cli.CliTest.test_full_day_on_a_recorded_session` |
| US-02-AC1 VIX 16.0 / VIX3M 18.5 reads contango, values and timestamp shown | `test_regime.RegimeTest.test_us02_ac1_normal_market_reads_contango_with_values_and_timestamp` |
| US-02-AC2 VIX 38 / VIX3M 30 reads backwardation | `test_regime.RegimeTest.test_us02_ac2_stressed_market_reads_backwardation` |
| US-02-AC3 missing point reported as unknown and named | `test_regime.RegimeTest.test_us02_ac3_missing_point_is_unknown_and_named`, `test_scan.StandDownTest.test_us02_ac3_missing_vix3m_is_named_in_the_output` |
| US-03-AC1 recorded VIX 16 contango session gives a proposal with no blank fields | `test_scan.ProposalTest.test_us03_ac1_recorded_contango_session_gives_a_full_proposal` |
| US-03-AC2 ranked by expected annual return on BP, runner-up shown with numbers | `test_scan.ProposalTest.test_us03_ac2_ranked_by_annual_return_on_bp_and_runner_up_shown` |
| US-03-AC3 nothing fits means no proposal, stated | `test_scan.StandDownTest.test_us03_ac3_nothing_fits_says_so` |
| US-03-AC4 candidate exactly at the cap is allowed | `test_sizing_margin.SizingTest.test_us03_ac4_candidate_exactly_at_the_cap_is_allowed`, `test_one_cent_over_the_cap_is_refused` |
| US-04-AC1 VIX 35 stands down naming the 28 ceiling | `test_regime.RegimeTest.test_us04_ac1_panic_names_the_ceiling`, `test_scan.StandDownTest.test_us04_ac1_ac3_panic_stands_down_and_is_logged` |
| US-04-AC2 VIX 12 stands down naming the 13 floor | `test_regime.RegimeTest.test_us04_ac2_crushed_names_the_floor`, `test_scan.StandDownTest.test_us04_ac2_crushed_stands_down` |
| US-04-AC3 stand-downs logged with timestamp, regime, reasons | `test_scan.StandDownTest.test_us04_ac1_ac3_panic_stands_down_and_is_logged` |
| US-05-AC1 every risk field present with units | `test_analytics.RiskTest.test_us05_ac1_every_risk_field_is_present`, `test_scan.ProposalTest.test_us05_ac1_ac2_risk_block_labeled_with_units_and_assumptions` |
| US-05-AC2 assumptions paragraph under the risk block | `test_analytics.RiskTest.test_us05_ac2_assumptions_are_stated` |
| US-05-AC3 missing assumption named, never defaulted | `test_analytics.RiskTest.test_us05_ac3_missing_assumption_is_named_not_defaulted`, `test_scan.StandDownTest.test_us05_ac3_missing_assumption_blocks_the_risk_block` |
| US-06-AC1 healthy data passes | `test_feed.ProbeTest.test_us06_ac1_healthy_payload_passes` |
| US-06-AC2 31 minutes old or a missing field means no advice | `test_feed.ProbeTest.test_us06_ac2_stale_by_one_minute_fails`, `test_us06_ac2_missing_field_fails`, `test_scan.StandDownTest.test_us06_ac2_stale_data_gives_no_advice` |
| US-06-AC3 exactly 30 minutes old passes | `test_feed.ProbeTest.test_us06_ac3_exactly_thirty_minutes_passes`, `test_scan.StandDownTest.test_us06_ac3_exactly_thirty_minutes_still_advises` |
| US-07-AC1 delivered and delivery time recorded | `test_notify.DeliveryTest.test_us07_ac1_delivered_and_timed` |
| US-07-AC2 no repeat of the full alert when nothing changed (short no-change note instead) | `test_notify.DeliveryTest.test_us07_ac2_unchanged_scan_sends_a_short_no_change_note_not_the_full_alert`, `test_suppress_policy_sends_nothing_for_a_repeat` |
| US-07-AC3 failed delivery retried and flagged | `test_notify.DeliveryTest.test_us07_ac3_retried_then_delivered`, `test_us07_ac3_final_failure_is_flagged` |
| US-08-AC1 one complete row per alert | `test_scan.ProposalTest.test_us08_ac1_one_complete_row_per_scan`, `test_scan.LogTest.test_log_is_append_only` |
| US-08-AC2 query by date range, in order | `test_scan.LogTest.test_us08_ac2_query_by_date_in_order` |
| US-09-AC1 daily mark as if opened | `test_mark.MarkTest.test_us09_ac1_daily_mark_as_if_opened` |
| US-09-AC2 settled result at expiration | `test_mark.MarkTest.test_us09_ac2_settles_at_expiration` |
| QR-1 no advice from quotes older than 30 minutes | `test_feed.ProbeTest.test_fresh_cdn_timestamp_does_not_hide_old_quotes`, `test_feed.ReplayTest.test_replay_at_recording_time_is_stale` |
| QR-5 no credentials or balances in version control | `.gitignore` covers profiles, databases, `.env`; credentials are environment variables |
| QR-6 plain-text alerts | `test_scan.ProposalTest.test_b_kr3_quotes_and_both_timestamps_in_the_message` |
| A-KR2 checks catch planted rows | `test_kr.AlphaKRTest.test_a_kr2_real_proposal_passes_and_every_planted_row_is_caught` |
| A-KR3 24 cases, 0 violations | `test_kr_a3.AKR3Matrix` (24 tests); table in `docs/results/a-kr3.md` |
| B-KR1 to B-KR3 scripts | `test_kr.BetaKRTest`, `test_notify.DeliveryTest.test_no_change_note_for_a_proposal_keeps_the_legs_and_quotes` |
| Addition: worst-case limit sizes down or refuses (not yet in the proposal) | `test_sizing_margin.WorstCaseSizingTest` (6 tests), `test_scan.ProposalTest.test_worst_case_limit_cuts_the_size`, `test_scan.StandDownTest.test_tight_worst_case_limit_means_nothing_fits`, `test_profile.ProfileTest.test_worst_case_limit_defaults_to_ten_percent_and_is_validated` |
| A-KR2 worst-case check catches a planted row | `test_kr.AlphaKRTest.test_a_kr2_real_proposal_passes_and_every_planted_row_is_caught` (8 of 8) |
