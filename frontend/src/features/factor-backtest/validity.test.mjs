import assert from "node:assert/strict";
import { test } from "node:test";
import { validityRow, formatMetric, compareMetrics, confirmedFactors, isConfirmedRun, qualificationReason } from "./validity.ts";

test("validation values come exclusively from the real validation segment", () => {
  const row = validityRow({ ic: 0.8, icir: 4, segments: { valid: { ic: -0.03, icir: -0.7, valid_days: 42 } } });
  assert.equal(row.valid_ic, -0.03);
  assert.equal(row.valid_icir, -0.7);
  assert.equal(row.valid_days, 42);
});

test("missing and nonfinite metrics stay absent; zero remains real", () => {
  const row = validityRow({ ic: NaN, score: null, segments: { valid: { ic: Infinity, valid_days: 0 } } });
  assert.equal(row.ic, null);
  assert.equal(row.valid_ic, null);
  assert.equal(row.valid_icir, null);
  assert.equal(row.valid_days, 0);
  assert.equal(formatMetric(null, 4), "—");
  assert.equal(formatMetric(0, 4), "0.0000");
  assert.equal(compareMetrics(null, -0.1), 1);
  assert.equal(compareMetrics(null, undefined), 0);
});

test("backtest consumes confirmed records only and requires completed confirmation", () => {
  const candidate = {factor_id: "candidate"};
  const confirmed = {factor_id: "confirmed"};
  assert.deepEqual(confirmedFactors({candidate_factors:[candidate],accepted_factors:[candidate]}), []);
  assert.deepEqual(confirmedFactors({candidate_factors:[candidate],confirmed_factors:[confirmed]}), [confirmed]);
  assert.equal(isConfirmedRun({local_available:true,confirmed_count:1,confirmation_status:"pending"}), false);
  assert.equal(isConfirmedRun({local_available:true,candidate_count:10,confirmation_status:"finished"}), false);
  assert.equal(isConfirmedRun({local_available:true,confirmed_count:1,confirmation_status:"finished"}), true);
});

test("test metrics and qualification text use actual holdout data", () => {
  const factor = {ic: -0.1, segments: {valid:{ic:0.8},test:{ic:-0.04,rank_ic:-0.05,icir:-0.4,coverage:0.95,valid_days:60}}};
  const row = validityRow(factor);
  assert.equal(row.test_ic, -0.04);
  assert.equal(row.test_rank_ic, -0.05);
  assert.equal(row.test_days, 60);
  assert.match(qualificationReason(factor), /通过测试门槛/);
  assert.match(qualificationReason(factor), /同号/);
  assert.match(qualificationReason(factor, {min_test_ic:0.06}), /不一致/);
  assert.match(qualificationReason({ic:0.1}), /缺失/);
});
