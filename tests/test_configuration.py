import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

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


if __name__=='__main__': unittest.main()
