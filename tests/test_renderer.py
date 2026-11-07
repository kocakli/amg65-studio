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
    def test_selected_tool_is_never_replaced_by_another_tool_or_a_quota_time_slot(self):
        from renderer import select_activity
        rows={'providers':[{'provider':'claude','state':'running','expires_at':200},
                           {'provider':'codex','state':'waiting_approval','expires_at':200}]}
        for elapsed in (0,4,7,9,16):
            self.assertEqual(select_activity(rows,elapsed,100,provider='claude')['provider'],'claude')
        self.assertEqual(select_activity(rows,7,100)['provider'],'codex')
        self.assertIsNone(select_activity(rows,7,201,provider='claude'))
        self.assertIsNone(select_activity(rows,7,100,provider='cursor'))

    def test_observed_work_categories_have_distinct_fixed_labels(self):
        from renderer import activity_label,WORK_LABELS,render_activity,render_claude_mascot,text_width
        self.assertTrue(all(text_width(label)<=20 for label in WORK_LABELS.values()))
        frames=[]
        for summary,label in WORK_LABELS.items():
            row={'provider':'claude','state':'running','summary':summary}
            self.assertEqual(activity_label(row),label)
            frames.append(render_activity(row,{},1))
            mascot=render_claude_mascot(row,{},1)
            self.assertEqual([mascot[y*63+32:y*63+53] for y in range(5)],
                             [frames[-1][y*63+32:y*63+53] for y in range(5)])
        self.assertEqual(len(set(tuple(frame) for frame in frames)),len(WORK_LABELS))
        self.assertEqual(activity_label({'state':'running','summary':'PRIVATE COMMAND'}),'RUN')

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
        # Keep the hue around a clear orange, rather than the old red-orange.
        self.assertGreaterEqual(green/red,.55)
        self.assertLessEqual(green/red,.65)
        self.assertGreater(green,blue*2)
        # Fully saturated; the global brightness slider still controls intensity.
        self.assertGreaterEqual((max((red,green,blue))-min((red,green,blue)))/red,.97)

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


class ClaudeMascotTests(unittest.TestCase):
    def setUp(self):
        self.snapshot={'providers':[{'id':p,'remaining_percent':v} for p,v in
                                   (('claude',98),('codex',46),('cursor',54))]}

    def test_walk_changes_position_in_both_directions_and_loops(self):
        from renderer import render_claude_mascot,BLACK
        row={'provider':'claude','state':'running'}
        frames=[render_claude_mascot(row,self.snapshot,1,step/2) for step in range(12)]
        positions=[min(x for x in range(25) if any(frame[y*63+x]!=BLACK for y in range(5))) for frame in frames]
        self.assertEqual((min(positions),max(positions)),(1,13))
        self.assertTrue(any(b>a for a,b in zip(positions,positions[1:])))
        self.assertTrue(any(b<a for a,b in zip(positions,positions[1:])))
        self.assertEqual(frames[0],render_claude_mascot(row,self.snapshot,1,6))

    def test_all_poses_keep_quota_gauges_and_clear_gutters(self):
        from renderer import render_claude_mascot,ACTIVITY_LABELS,BLACK
        quota=render_overview(self.snapshot,1)
        for state in ACTIVITY_LABELS:
            for step in range(12):
                frame=render_claude_mascot({'provider':'claude','state':state},self.snapshot,1,step/2)
                self.assertEqual(len(frame),315)
                self.assertTrue(all(type(channel) is int and 0<=channel<=254 for pixel in frame for channel in pixel))
                for y in range(5):self.assertEqual(frame[y*63+56:y*63+63],quota[y*63+56:y*63+63])
                for x in (24,25,29,30,31,53,54,55,56):self.assertTrue(all(frame[y*63+x]==BLACK for y in range(5)))

    def test_waiting_error_and_queue_poses_are_stationary(self):
        from renderer import render_claude_mascot
        for state in ('waiting_approval','waiting_input','error','queued'):
            row={'provider':'claude','state':state}
            self.assertEqual(render_claude_mascot(row,self.snapshot,1,0),render_claude_mascot(row,self.snapshot,1,3.5))

    def test_other_providers_keep_their_text_and_private_metadata_is_ignored(self):
        from renderer import render_claude_mascot,render_activity
        for provider in ('codex','cursor'):
            row={'provider':provider,'state':'running'}
            self.assertEqual(render_claude_mascot(row,self.snapshot,1,1),render_activity(row,self.snapshot,1,1))
        row={'provider':'claude','state':'running'}
        self.assertEqual(render_claude_mascot(dict(row,summary='PRIVATE PROMPT'),self.snapshot,1,1),
                         render_claude_mascot(dict(row,summary='OTHER FILE'),self.snapshot,1,1))

    def test_unknown_never_becomes_a_working_mascot_and_brightness_zero_is_black(self):
        from renderer import render_claude_mascot,ACTIVITY_LABELS,BLACK
        self.assertEqual(render_claude_mascot({'provider':'claude','state':'unknown'},self.snapshot,1),[BLACK]*315)
        for state in ACTIVITY_LABELS:
            self.assertEqual(render_claude_mascot({'provider':'claude','state':state},self.snapshot,0,1),[BLACK]*315)


class ProductMascotTests(unittest.TestCase):
    def setUp(self):
        self.snapshot={'providers':[{'id':p,'remaining_percent':v} for p,v in
                                   (('claude',98),('codex',46),('cursor',54))]}

    def test_each_character_has_a_distinct_silhouette_independent_of_its_color(self):
        from renderer import MASCOT_SPRITES
        self.assertEqual(set(MASCOT_SPRITES),{'claude','codex','cursor'})
        self.assertEqual(len(set(MASCOT_SPRITES.values())),3)
        for sprite in MASCOT_SPRITES.values():
            self.assertEqual(len(sprite),5)
            self.assertTrue(all(len(row)==11 and set(row)<={'0','1'} for row in sprite))

    def test_all_products_walk_both_ways_with_fixed_identity_work_label_and_quota_rails(self):
        from renderer import render_mascot,BLACK,WORK_LABELS
        quota=render_overview(self.snapshot,1)
        for provider in ('claude','codex','cursor'):
            row={'provider':provider,'state':'running','summary':'reading_files'}
            frames=[render_mascot(row,self.snapshot,1,step/2) for step in range(12)]
            self.assertEqual(frames[0],render_mascot(row,self.snapshot,1,6))
            positions=[min(i%63 for i,pixel in enumerate(frame) if i%63<24 and pixel!=BLACK) for frame in frames]
            self.assertTrue(any(b>a for a,b in zip(positions,positions[1:])))
            self.assertTrue(any(b<a for a,b in zip(positions,positions[1:])))
            for frame in frames:
                for y in range(5):
                    self.assertEqual(frame[y*63+26:y*63+53],frames[0][y*63+26:y*63+53])
                    self.assertEqual(frame[y*63+56:y*63+63],quota[y*63+56:y*63+63])
            labels=[]
            for summary in WORK_LABELS:
                frame=render_mascot(dict(row,summary=summary),self.snapshot,1)
                labels.append(tuple(pixel for i,pixel in enumerate(frame) if 32<=i%63<53))
            self.assertEqual(len(set(labels)),len(WORK_LABELS))

    def test_every_pose_is_bounded_preserves_gutters_and_zero_brightness(self):
        from renderer import render_mascot,ACTIVITY_LABELS,BLACK
        for provider in ('claude','codex','cursor'):
            for state in ACTIVITY_LABELS:
                row={'provider':provider,'state':state}
                self.assertEqual(render_mascot(row,self.snapshot,0,1),[BLACK]*315)
                for step in range(12):
                    frame=render_mascot(row,self.snapshot,1,step/2)
                    self.assertEqual(len(frame),315)
                    self.assertTrue(all(type(v) is int and 0<=v<=254 for pixel in frame for v in pixel))
                    for x in (24,25,29,30,31,53,54,55,56):
                        self.assertTrue(all(frame[y*63+x]==BLACK for y in range(5)),(provider,state,step,x))

    def test_waits_stop_motion_and_unknown_or_private_data_never_invents_work(self):
        from renderer import render_mascot,BLACK
        for provider in ('claude','codex','cursor'):
            for state in ('queued','waiting_approval','waiting_input','error'):
                row={'provider':provider,'state':state}
                self.assertEqual(render_mascot(row,self.snapshot,1,0),render_mascot(row,self.snapshot,1,3.5))
            self.assertEqual(render_mascot({'provider':provider,'state':'unknown'},self.snapshot,1),[BLACK]*315)
            row={'provider':provider,'state':'running'}
            self.assertEqual(render_mascot(dict(row,summary='PRIVATE PATH'),self.snapshot,1),
                             render_mascot(dict(row,summary='PRIVATE PROMPT'),self.snapshot,1))
        self.assertEqual(render_mascot({'provider':'other','state':'running'},self.snapshot,1),[BLACK]*315)
