import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from configuration import settings_patch,lighting_request,LIGHTING
from app import Application,Bridge


class ConfigurationTests(unittest.TestCase):
    def test_text_is_bounded_and_ascii(self):
        for value in ('x'*65,'ö','hello\nworld'):
            with self.assertRaises(ValueError): settings_patch({'text':value})
        self.assertEqual(settings_patch({'text':'studio 65'})['text'],'STUDIO 65')

    def test_color_and_numeric_validation(self):
        for value in (True,float('nan'),-1,2):
            with self.assertRaises(ValueError): settings_patch({'brightness':value})
        for value in ('#fff','javascript:alert(1)',123):
            with self.assertRaises(ValueError): settings_patch({'text_color':value})
        self.assertEqual(settings_patch({'text_color':'#AABBCC'})['text_color'],'#aabbcc')

    def test_lighting_bounds_and_types(self):
        for key,value in [('mode',20),('brightness',0),('speed',True),('colorful',1)]:
            with self.assertRaises(ValueError): lighting_request(dict(LIGHTING,**{key:value}))
        self.assertEqual(lighting_request(dict(LIGHTING)),LIGHTING)

    def test_unknown_fields_rejected(self):
        with self.assertRaises(ValueError): settings_patch({'firmware':'anything'})

    def test_text_effect_is_opt_in_and_bounded(self):
        from configuration import DEFAULTS
        self.assertEqual(DEFAULTS['text_effect'],'none')
        for effect in ('none','scan','breathe','matrix','scroll'):
            self.assertEqual(settings_patch({'text_effect':effect}),{'text_effect':effect})
        for effect in (True,None,'rainbow','<script>'):
            with self.assertRaises(ValueError):settings_patch({'text_effect':effect})

    def test_old_saved_settings_use_plain_text_and_effect_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            saved=Path(directory)/'settings.json'
            saved.write_text(json.dumps({'display_mode':'text','text':'HELLO'}))
            with patch('app.UsageAdapter'):
                app=Application(directory,no_device=True)
                self.assertEqual(app.settings['text_effect'],'none')
                self.assertFalse(app.settings['mascot_enabled'])
                app.settings.update(settings_patch({'text_effect':'matrix','mascot_enabled':True}))
                app.save_settings()
                restored=Application(directory,no_device=True)
                self.assertEqual(restored.settings['text_effect'],'matrix')
                self.assertTrue(restored.settings['mascot_enabled'])
                self.assertEqual(restored.settings['text'],'HELLO')

    def test_mascot_preference_accepts_only_explicit_booleans(self):
        for key in ('mascot_enabled','claude_mascot'):
            for value in (True,False):
                self.assertEqual(settings_patch({key:value}),{'mascot_enabled':value})
            for value in (0,1,'true',None,[]):
                with self.assertRaises(ValueError):settings_patch({key:value})

    def test_old_mascot_switch_migrates_and_explicit_generic_switch_wins(self):
        self.assertEqual(settings_patch({'claude_mascot':None,'mascot_enabled':False}),{'mascot_enabled':False})
        with self.assertRaises(ValueError):settings_patch({'claude_mascot':True,'mascot_enabled':None})
        for legacy in (False,True):
            with tempfile.TemporaryDirectory() as directory,patch('app.UsageAdapter'):
                saved=Path(directory)/'settings.json'
                saved.write_text(json.dumps({'claude_mascot':legacy,'brightness':.3}))
                app=Application(directory,no_device=True)
                self.assertIs(app.settings['mascot_enabled'],legacy)
                self.assertNotIn('claude_mascot',app.settings)
                self.assertEqual(app.settings['brightness'],.3)
                new=not legacy
                app.settings.update(settings_patch({'claude_mascot':legacy,'mascot_enabled':new}))
                app.save_settings()
                persisted=json.loads(saved.read_text())
                self.assertIs(persisted['mascot_enabled'],new)
                self.assertNotIn('claude_mascot',persisted)
                restored=Application(directory,no_device=True)
                self.assertIs(restored.settings['mascot_enabled'],new)

    def test_tracked_provider_is_bounded_and_old_settings_default_to_automatic(self):
        from configuration import DEFAULTS
        self.assertEqual(DEFAULTS['tracked_provider'],'all')
        for provider in ('all','claude','codex','cursor'):
            self.assertEqual(settings_patch({'tracked_provider':provider}),{'tracked_provider':provider})
        for provider in ('other',None,True,1,[]):
            with self.assertRaises(ValueError):settings_patch({'tracked_provider':provider})

    def test_claude_color_balance_has_neutral_default_and_strict_bounds(self):
        from configuration import DEFAULTS
        from renderer import DEFAULT_CLAUDE_GREEN_GAIN
        self.assertEqual(DEFAULTS['claude_green_gain'],1.0)
        self.assertEqual(DEFAULTS['claude_green_gain'],DEFAULT_CLAUDE_GREEN_GAIN)
        for gain in (0,.29,1):
            self.assertEqual(settings_patch({'claude_green_gain':gain}),{'claude_green_gain':gain})
        for gain in (True,False,None,'0.29',[],float('nan'),float('inf'),-.01,1.01,10**1000):
            with self.assertRaises(ValueError):settings_patch({'claude_green_gain':gain})

    def test_color_balance_survives_restart_without_changing_other_preferences(self):
        with tempfile.TemporaryDirectory() as directory,patch('app.UsageAdapter') as adapter:
            adapter.return_value.snapshot.return_value={'providers':[]}
            app=Application(directory,no_device=True)
            self.assertEqual(app.settings['claude_green_gain'],1.0)
            app.settings.update(settings_patch({'claude_green_gain':.29,'brightness':1,'tracked_provider':'claude'}))
            app.save_settings()
            restored=Application(directory,no_device=True)
            for key in ('claude_green_gain','brightness','tracked_provider'):
                self.assertEqual(restored.settings[key],app.settings[key])
            self.assertEqual(restored.state['matrix']['claude_green_gain'],.29)


class OwnershipTests(unittest.TestCase):
    def make_app(self,path):
        with patch('app.UsageAdapter') as adapter:
            adapter.return_value.snapshot.return_value={'providers':[]}
            return Application(path,no_device=True)

    def test_native_ownership_only_published_after_usb_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            app=self.make_app(directory)
            actions=[]
            class Transport:
                def send(self,op): actions.append(op)
                def close(self):
                    self_outer.assertEqual(app.snapshot()['hardware_owner'],'dashboard')
                    actions.append('closed')
            self_outer=self
            app.bridge=Transport()
            app.release_to_native(100)
            self.assertEqual(actions,['stop','closed'])
            self.assertIsNone(app.bridge)

            self.assertEqual(app.native_until,145)
            self.assertEqual(app.snapshot()['hardware_owner'],'native')

    def test_unacknowledged_connection_cannot_be_handed_to_another_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            app=self.make_app(directory)
            app.blocked_identity=123
            with self.assertRaises(ValueError): app.release_to_native(100)
            self.assertEqual(app.snapshot()['hardware_owner'],'dashboard')

    def test_uncertain_transport_failure_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            app=self.make_app(directory)
            class Transport:
                identity=987
                def close(self): pass
            app.bridge=Transport()
            app.disconnect(OSError('unexpected EOF'))
            restored=self.make_app(directory)
            self.assertEqual(restored.blocked_identity,987)

    def test_non_object_saved_state_does_not_crash_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ([],None,42,'invalid'):
                with self.subTest(value=value):
                    for name in ('settings.json','usb-blocked.json'):
                        (Path(directory)/name).write_text(json.dumps(value))
                    app=self.make_app(directory)
                    self.assertEqual(app.settings['display_mode'],'overview')
                    self.assertIsNone(app.blocked_identity)
                    app.no_device=False
                    with patch('app.Bridge') as transport:
                        app.connect()
                        transport.assert_not_called()

    def test_new_native_fault_is_read_before_reconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            app=self.make_app(directory)
            app.no_device=False
            (Path(directory)/'usb-blocked.json').write_text(json.dumps({'registry_id':654}))
            with patch('app.Bridge') as transport:
                transport.return_value.identity=654
                app.connect()
                transport.return_value.send.assert_not_called()
                transport.return_value.close.assert_called_once()
            self.assertEqual(app.blocked_identity,654)
            self.assertIsNone(app.bridge)


class MascotWorkerTests(unittest.TestCase):
    def test_saved_balance_reaches_activity_overview_focused_and_rotating_views(self):
        import time
        from renderer import render_activity,render_mascot,render_overview,render_detail,render_text
        providers=[{'id':p,'remaining_percent':v} for p,v in (('claude',98),('codex',46),('cursor',54))]
        cases=[('activity',True,'overview','claude',0),('activity',False,'overview','claude',0),
               ('overview',False,'overview','all',0),('claude',False,'overview','claude',0),
               ('claude',False,'rotate','all',12),('text',False,'text','all',0)]
        for view,mascot,mode,target,tick in cases:
            with self.subTest(view=view,mascot=mascot,mode=mode),tempfile.TemporaryDirectory() as directory, \
                 patch('app.UsageAdapter') as adapter,patch('app.ActivityCollector') as collector:
                adapter.return_value.snapshot.return_value={'providers':providers}
                row={'provider':'claude','state':'running','summary':'working','expires_at':time.time()+60}
                collector.return_value.snapshot.return_value={'providers':[row] if view=='activity' else []}
                app=Application(directory,no_device=True)
                app.settings.update(mascot_enabled=mascot,tracked_provider=target,display_mode=mode,
                                    brightness=1,claude_green_gain=.29,text='TEXT',text_color='#fe5a00')
                app.quit=Mock();app.quit.is_set.side_effect=[False,True]
                with patch('app.time.monotonic',side_effect=[0,tick]):app.run()
                state=app.snapshot()
                if view=='activity':expected=(render_mascot if mascot else render_activity)(row,state,1,0,claude_green_gain=.29)
                elif view=='overview':expected=render_overview(state,1,claude_green_gain=.29)
                elif view=='text':expected=render_text('TEXT','#fe5a00',1,0)
                else:expected=render_detail(providers[0],1,claude_green_gain=.29)
                self.assertEqual(state['matrix']['pixels'],expected)
                self.assertEqual(state['matrix']['view'],view)
                self.assertEqual(state['matrix']['claude_green_gain'],.29)

    def test_live_display_switch_routes_each_selected_product_without_text_effects(self):
        import time
        from renderer import render_activity,render_mascot
        for provider in ('claude','codex','cursor'):
            for enabled in (False,True):
                with self.subTest(provider=provider,enabled=enabled),tempfile.TemporaryDirectory() as directory, \
                     patch('app.UsageAdapter') as adapter,patch('app.ActivityCollector') as collector:
                    adapter.return_value.snapshot.return_value={'providers':[]}
                    row={'provider':provider,'state':'running','summary':'reading_files','expires_at':time.time()+60}
                    collector.return_value.snapshot.return_value={'providers':[row]}
                    app=Application(directory,no_device=True)
                    app.settings.update(mascot_enabled=enabled,tracked_provider=provider,
                                        text_effect='matrix' if enabled else 'none')
                    app.quit=Mock()
                    app.quit.is_set.side_effect=[False,True]
                    app.run()
                    state=app.snapshot()
                    expected=(render_mascot if enabled else render_activity)(row,state,.4,0)
                    self.assertEqual(state['matrix']['pixels'],expected)
                    self.assertEqual(state['matrix']['activity']['provider'],provider)
                    self.assertEqual(state['matrix']['view'],'activity')


if __name__=='__main__': unittest.main()
