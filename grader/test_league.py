"""Badges and league rules (pure, no server).

    python -m unittest grader/test_league.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league  # noqa: E402

T0 = 1791500000.0      # 2026-10


def att(aid, user="a@x", scenario="dns-poison", t=T0, tier="merit", score=85.0, attested=True, mttr=200.0,
        hints=0, restarted=(), recreated=(), trust=None):
    return {"id": aid, "user": user, "scenario": scenario, "submitted": t,
            "result": {"attested": attested, "tier": tier, "score": score, "hints_used": hints,
                       "sli": {"mttr_s": mttr}, "blast_radius": {"restarted_unaffected": list(restarted),
                                                                 "recreated": list(recreated)},
                       "trust": trust or {"assertions": "client-reported", "hidden": "client-reported"}}}


def ids(bs):
    return sorted((b["badge"], b["scenario"]) for b in bs)


class Badges(unittest.TestCase):
    def test_unattested_or_failed_attempts_earn_nothing(self):
        bs = league.badges([att("1", attested=False, tier="unverified"), att("2", tier="fail", score=30)], {})
        self.assertEqual(bs, [])

    def test_clean_fast_attested_pass(self):
        self.assertEqual(ids(league.badges([att("1")], {})),
                         [("fast_hands", "dns-poison"), ("first_recovery", None), ("surgeon", "dns-poison")])

    def test_hint_or_collateral_restart_is_not_surgical(self):
        for a in (att("1", hints=1), att("1", restarted=["prober"]), att("1", recreated=["api"])):
            self.assertNotIn("surgeon", [b["badge"] for b in league.badges([a], {})])

    def test_range_certified_needs_platform_and_private_pack(self):
        public = att("1", trust={"assertions": "platform", "hidden": "platform, public pack"})
        private = att("2", trust={"assertions": "platform", "hidden": "platform, private pack"})
        self.assertNotIn("range_certified", [b["badge"] for b in league.badges([public], {})])
        self.assertIn("range_certified", [b["badge"] for b in league.badges([private], {})])

    def test_debrief_badges(self):
        ok = {"verdict": "verified", "facts": {"missing": []}, "timeline": {"mitigated_error_s": 4}}
        loose = {"verdict": "verified", "facts": {"missing": ["poisoned_ttl"]}, "timeline": {"mitigated_error_s": 4}}
        self.assertIn("coroner", [b["badge"] for b in league.badges([att("1")], {"1": ok})])
        got = [b["badge"] for b in league.badges([att("1")], {"1": loose})]
        self.assertIn("forensic", got)
        self.assertNotIn("coroner", got)
        self.assertNotIn("forensic", [b["badge"] for b in league.badges([att("1")], {"1": {"verdict": "insufficient"}})])
        legacy = {"verdict": "verified", "timeline": {"mitigated_error_s": 1}}      # checked before facts existed
        self.assertNotIn("coroner", [b["badge"] for b in league.badges([att("1")], {"1": legacy})])

    def test_each_badge_points_at_the_earliest_attempt(self):
        bs = league.badges([att("late", t=T0 + 100), att("early", t=T0)], {})
        self.assertTrue(all(b["attempt_id"] == "early" for b in bs))

    def test_polymath_after_three_scenarios(self):
        a = [att("1", scenario="dns-poison"), att("2", scenario="clock-drift", t=T0 + 1),
             att("3", scenario="dns-poison", t=T0 + 2)]
        self.assertNotIn("polymath", [b["badge"] for b in league.badges(a, {})])
        a.append(att("4", scenario="retry-storm", t=T0 + 3))
        poly = [b for b in league.badges(a, {}) if b["badge"] == "polymath"]
        self.assertEqual(poly[0]["attempt_id"], "4")


class League(unittest.TestCase):
    def test_best_attested_score_per_scenario_plus_debrief(self):
        a = [att("1", user="a@x", score=70), att("2", user="a@x", score=90, t=T0 + 1),
             att("3", user="a@x", scenario="clock-drift", score=80, attested=False, tier="unverified"),
             att("4", user="b@x", score=95)]
        lg = league.league(league.season(T0), a, {"1": {"verdict": "verified"}})
        rows = {r["alias"]: r for r in lg["rows"]}
        self.assertEqual(rows[league.alias("a@x")]["points"], 100.0)   # 90 + 10, the unattested 80 does not count
        self.assertEqual(rows[league.alias("b@x")]["points"], 95.0)
        self.assertEqual([r["rank"] for r in lg["rows"]], [1, 2])
        self.assertNotIn("a@x", str(lg))                                   # aliases only

    def test_other_months_do_not_count(self):
        lg = league.league("2026-11", [att("1")], {})
        self.assertEqual(lg["rows"], [])


if __name__ == "__main__":
    unittest.main()
