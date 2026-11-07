import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from renderer import render_overview, render_detail, WIDTH


class RendererTests(unittest.TestCase):
    def test_all_full_values_fit_main_panel_without_crossing_separator(self):
        providers = [{"id": p, "remaining_percent": 100} for p in ("claude", "codex", "cursor")]
        pixels = render_overview({"providers": providers}, 1)
        self.assertEqual(len(pixels), 315)
        self.assertTrue(all(isinstance(c, int) and 0 <= c <= 254 for rgb in pixels for c in rgb))
        self.assertTrue(all(pixels[y * WIDTH + 56] == (0, 0, 0) for y in range(5)))
        for start in (0, 19, 38):
            self.assertTrue(any(pixels[y * WIDTH + start + 14] != (0, 0, 0) for y in range(5)))

    def test_unknown_is_not_zero_and_invalid_values_are_unknown(self):
        missing = render_detail({"id": "claude"})
        zero = render_detail({"id": "claude", "remaining_percent": 0})
        self.assertNotEqual(missing, zero)
        for invalid in (-1, 101, math.nan, math.inf, True, "25"):
            self.assertEqual(missing, render_detail({"id": "claude", "remaining_percent": invalid}))

    def test_snapshot_provider_order_does_not_change_display(self):
        a = [{"id": "claude", "remaining_percent": 20}, {"id": "cursor", "remaining_percent": 85}]
        self.assertEqual(render_overview({"providers": a}), render_overview({"providers": list(reversed(a))}))

    def test_stale_values_are_dimmer_and_marked(self):
        good = render_overview({"providers": [{"id": "claude", "remaining_percent": 50}]})
        stale = render_overview({"providers": [{"id": "claude", "remaining_percent": 50, "stale": True}]})
        self.assertLess(sum(stale[1]), sum(good[1]))
        self.assertNotEqual(stale[17], (0, 0, 0))

    def test_zero_brightness_and_invalid_brightness(self):
        self.assertEqual(render_overview({}, 0), [(0, 0, 0)] * 315)
        for invalid in (-1, 1.1, math.nan, True):
            with self.assertRaises(ValueError):
                render_overview({}, invalid)

    def test_unknown_and_zero_right_meters_are_distinct(self):
        unknown = render_overview({})
        zero = render_overview({"providers": [{"id": "claude", "remaining_percent": 0}]})
        self.assertNotEqual([unknown[y * 63 + 57] for y in range(5)], [zero[y * 63 + 57] for y in range(5)])


if __name__ == "__main__":
    unittest.main()

class ActivityRendererTests(unittest.TestCase):
    def test_attention_preempts_running_and_expired_states_disappear(self):
        from renderer import select_activity
        activity={'providers':[
            {'provider':'codex','state':'running','expires_at':200},
            {'provider':'claude','state':'waiting_approval','expires_at':200}]}
        self.assertEqual(select_activity(activity,7,100)['provider'],'claude')
        self.assertIsNone(select_activity(activity,0,201))

    def test_working_states_share_time_with_quota_display(self):
        from renderer import select_activity
        activity={'providers':[{'provider':'codex','state':'running','expires_at':200}]}
        self.assertIsNotNone(select_activity(activity,2,100))
        self.assertIsNone(select_activity(activity,7,100))

    def test_no_invented_unknown_and_fair_waiting_rotation(self):
        from renderer import select_activity
        self.assertIsNone(select_activity({'providers':[{'provider':'codex','state':'unknown','expires_at':200}]},0,100))
        rows=[{'provider':p,'state':'waiting_input','expires_at':200} for p in ('codex','claude')]
        self.assertEqual(select_activity({'providers':rows},0,100)['provider'],'codex')
        self.assertEqual(select_activity({'providers':rows},4,100)['provider'],'claude')

    def test_all_activity_frames_are_bounded_and_do_not_render_private_text(self):
        from renderer import render_activity,ACTIVITY_LABELS
        for state in ACTIVITY_LABELS:
            row={'provider':'codex','state':state,'summary':'PRIVATE FILE/PROMPT'}
            frame=render_activity(row,{},0.4,1)
            self.assertEqual(len(frame),315)
            self.assertTrue(all(len(pixel)==3 and all(0<=v<=254 for v in pixel) for pixel in frame))
            self.assertEqual(frame,render_activity(dict(row,summary='DIFFERENT'),{},0.4,1))
