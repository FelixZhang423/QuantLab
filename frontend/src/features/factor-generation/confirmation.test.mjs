import assert from "node:assert/strict";
import { test } from "node:test";
import { confirmationRow } from "./confirmation.ts";

test("failed test metrics are displayed without promoting the factor", () => {
  const factor = {factor_id: "a", segments: {train: {ic: 0.08}}};
  const row = confirmationRow(factor, {confirmed_factors: [], test_evaluations: [
    {factor_id: "a", test: {ic: 0.01}, confirmed: false, reason: "IC below threshold"},
  ]});
  assert.equal(row.segments.test.ic, 0.01);
  assert.equal(row.segments.train.ic, 0.08);
  assert.equal(row.phase, "candidate");
  assert.match(row.confirmationText, /测试未通过.*IC below threshold/);
});

test("pending, errors and confirmed results remain distinct", () => {
  const f = {factor_id: "a"};
  assert.equal(confirmationRow(f, {confirmed_factors: []}).confirmationText, "尚未评估");
  const error = confirmationRow(f, {confirmed_factors: [], test_evaluations: [
    {factor_id: "a", test: null, confirmed: false, reason: "evaluation error"},
  ]});
  assert.equal(error.segments.test, undefined);
  assert.match(error.confirmationText, /失败.*evaluation error/);
  const row = confirmationRow(f, {confirmed_factors: [{...f, segments: {test: {ic: -0.06}}}]});
  assert.equal(row.phase, "confirmed");
  assert.equal(row.segments.test.ic, -0.06);
});
