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

    def test_longest_labels_leave_a_clear_gap_before_quota_meters(self):
        from renderer import render_activity, ACTIVITY_LABELS
        for provider in ('claude','codex','cursor'):
            for state in ACTIVITY_LABELS:
                frame=render_activity({'provider':provider,'state':state},{},1)
                for x in (5,6,30,31,53,54,55,56):
                    self.assertTrue(all(frame[y*63+x]==(0,0,0) for y in range(5)),(provider,state,x))
                self.assertTrue(any(frame[y*63+x]!=(0,0,0) for y in range(5) for x in range(32,53)))

    def test_attention_states_remain_steady_and_work_motion_is_confined_to_icon(self):
        from renderer import render_activity
        for state in ('waiting_approval','waiting_input','completed','error','queued'):
            row={'provider':'claude','state':state}
            self.assertEqual(render_activity(row,{},1,0),render_activity(row,{},1,0.5))
        row={'provider':'claude','state':'running'}
        first,second=render_activity(row,{},1,0),render_activity(row,{},1,0.5)
        self.assertNotEqual(first,second)
        changed=[index%63 for index,(a,b) in enumerate(zip(first,second)) if a!=b]
        self.assertTrue(changed and max(changed)<5)

    def test_every_activity_state_respects_zero_brightness(self):
        from renderer import render_activity,ACTIVITY_LABELS
        for state in ACTIVITY_LABELS:
            self.assertEqual(render_activity({'provider':'claude','state':state},{},0,1),[(0,0,0)]*315)


class LayoutAndPaletteTests(unittest.TestCase):
    def test_claude_uses_a_saturated_orange_led_accent(self):
        from renderer import COLORS
        red,green,blue=COLORS['claude']
        self.assertGreater(red,green*2)
        self.assertGreater(green,blue*2)

    def test_percentage_units_have_a_stable_right_edge_as_values_change(self):
        from renderer import BLACK
        for value in (0,9,10,99,100):
            frame=render_overview({'providers':[{'id':'claude','remaining_percent':value}]},1)
            self.assertTrue(any(frame[y*63+15]!=BLACK for y in range(5)))
            self.assertTrue(all(frame[y*63+16]==BLACK for y in range(5)))

    def test_text_indicator_is_not_the_unknown_character(self):
        from renderer import render_text
        frame=render_text('','#7bdcb0',1)
        # A five-column T belongs to text mode. The old unsupported '*' fell back
        # to '?' and incorrectly suggested missing data on every personal message.
        indicator=[[frame[y*63+x]!=(0,0,0) for x in range(58,63)] for y in range(5)]
        self.assertEqual(indicator[0],[True]*5)
        self.assertEqual(indicator[4],[False,False,True,False,False])


class TextEffectTests(unittest.TestCase):
    def setUp(self):
        self.snapshot={'providers':[{'id':p,'remaining_percent':v} for p,v in
                                   (('claude',98),('codex',46),('cursor',54))]}

    def test_none_is_lossless_and_input_frame_is_never_mutated(self):
        from renderer import apply_text_effect
        frame=render_overview(self.snapshot)
        original=list(frame)
        self.assertEqual(apply_text_effect(frame,'none'),original)
        for effect in ('scan','breathe','matrix','scroll'):
            apply_text_effect(frame,effect,0.4,2)
            self.assertEqual(frame,original)

    def test_matrix_preserves_letter_pixels_and_all_effects_preserve_quota_gauges(self):
        from collections import Counter
        from renderer import apply_text_effect,BLACK
        frame=render_overview(self.snapshot)
        for effect in ('none','scan','breathe','matrix','scroll'):
            for elapsed in (0,0.49,0.5,1,4,11):
                result=apply_text_effect(frame,effect,0.4,elapsed)
                self.assertEqual(len(result),315)
                for y in range(5):
                    self.assertEqual(result[y*63+56:y*63+63],frame[y*63+56:y*63+63])
                self.assertTrue(all(0<=v<=254 for pixel in result for v in pixel))
                if effect=='matrix':
                    original_colors=Counter(color for color in frame if color!=BLACK)
                    actual_colors=Counter(result)
                    for color,count in original_colors.items():self.assertGreaterEqual(actual_colors[color],count)

    def test_matrix_moves_the_letters_downward_and_settles_between_waves(self):
        from renderer import apply_text_effect,BLACK
        frame=render_overview(self.snapshot)
        moving=apply_text_effect(frame,'matrix',0.4,1)
        self.assertTrue(any(pixel!=BLACK and moving[index]!=pixel for index,pixel in enumerate(frame) if index%63<56))
        # At the end of the cycle the letter pixels return to their exact rows.
        settled=apply_text_effect(frame,'matrix',0.4,4.5)
        for index,color in enumerate(frame):
            if color!=BLACK:self.assertEqual(settled[index],color)

    def test_activity_text_can_flow_without_moving_its_status_icon(self):
        from renderer import apply_text_effect,render_activity,BLACK
        frame=render_activity({'provider':'codex','state':'running'},self.snapshot,0.4,0)
        moving=apply_text_effect(frame,'matrix',0.4,1,left=7)
        for index,pixel in enumerate(frame):
            if index%63<7 or index%63>=56:self.assertEqual(moving[index],pixel)
        self.assertTrue(any(moving[i]!=p for i,p in enumerate(frame) if 7<=i%63<56 and p!=BLACK))

    def test_motion_is_quantized_and_respects_zero_brightness(self):
        from renderer import apply_text_effect
        frame=render_overview(self.snapshot)
        for effect in ('scan','breathe','matrix','scroll'):
            self.assertEqual(apply_text_effect(frame,effect,0.4,0),apply_text_effect(frame,effect,0.4,0.49))
            black=render_overview(self.snapshot,0)
            self.assertEqual(apply_text_effect(black,effect,0,0.5),black)

    def test_effect_selection_rejects_unknown_values(self):
        from renderer import apply_text_effect
        for effect in ('flash','<script>',None):
            with self.assertRaises(ValueError):apply_text_effect(render_overview({}),effect)

    def test_short_personal_text_scrolls_immediately_and_loops_without_changing_the_mode_icon(self):
        from renderer import render_text,text_width
        first=render_text('HELLO','#7bdcb0',0.4,0,marquee=True)
        next_frame=render_text('HELLO','#7bdcb0',0.4,.5,marquee=True)
        self.assertNotEqual(first,next_frame)
        for y in range(5):self.assertEqual(first[y*63+56:y*63+63],next_frame[y*63+56:y*63+63])
        period=text_width('HELLO')+10
        self.assertEqual(first,render_text('HELLO','#7bdcb0',0.4,period/2,marquee=True))

    def test_long_personal_marquee_keeps_content_beyond_the_first_viewport(self):
        from renderer import render_text,text_width
        prefix='AMG65 STUDIO AMG65 STUDIO '
        # The changed tail starts outside the initial viewport, then arrives.
        first=render_text(prefix+'ABC','#7bdcb0',.4,0,marquee=True)
        self.assertEqual(first,render_text(prefix+'XYZ','#7bdcb0',.4,0,marquee=True))
        later=text_width(prefix)/2
        self.assertNotEqual(render_text(prefix+'ABC','#7bdcb0',.4,later,marquee=True),
                            render_text(prefix+'XYZ','#7bdcb0',.4,later,marquee=True))
