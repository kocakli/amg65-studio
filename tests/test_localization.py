"""Offline release checks for catalogs and the strings consumed by both UIs.

These checks do not import the app, construct the USB bridge, or contact providers.
"""
from collections import Counter
import ast
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'NativeApp/Sources/AMG65Studio'
LOCALES = {'tr', 'en', 'es', 'zh-Hans', 'ja'}
CATALOGS = NATIVE / 'Resources/localizations'
PLACEHOLDER = re.compile(r'\{([0-9]+)\}')
WEB_PLACEHOLDER = re.compile(r'\{([a-zA-Z_][a-zA-Z_0-9]*)\}')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate localization key: {key!r}')
        result[key] = value
    return result


def swift_literal(source, start):
    """Read an ordinary Swift literal, replacing each interpolation with {N}.

    Nested quoted strings and parentheses inside interpolation are skipped, so a
    fallback such as ``value ?? "unknown"`` cannot truncate a visible UI message.
    """
    assert source[start] == '"'
    value = []
    position = start + 1
    interpolation = 0
    while position < len(source):
        char = source[position]
        if char == '"':
            return ''.join(value), position + 1
        if char != '\\':
            value.append(char)
            position += 1
            continue
        escaped = source[position + 1]
        if escaped == '(':
            position += 2
            depth = 1
            while depth:
                if source[position] == '"':
                    _, position = swift_literal(source, position)
                    continue
                depth += (source[position] == '(') - (source[position] == ')')
                position += 1
            value.append('{' + str(interpolation) + '}')
            interpolation += 1
        elif escaped == 'u' and source[position + 2] == '{':
            end = source.index('}', position + 3)
            value.append(chr(int(source[position + 3:end], 16)))
            position = end + 1
        else:
            value.append({'n': '\n', 'r': '\r', 't': '\t', '0': '\0'}.get(escaped, escaped))
            position += 2
    raise ValueError('Unterminated Swift string')


class NativeLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogs = {
            path.stem: json.loads(path.read_text(), object_pairs_hook=unique_object)
            for path in CATALOGS.glob('*.json')
        }

    def test_supported_catalogs_exist_and_have_identical_keys(self):
        self.assertEqual(set(self.catalogs), LOCALES)
        reference = set(self.catalogs['en'])
        self.assertTrue(reference, 'The localization catalog must not be empty')
        for language, catalog in self.catalogs.items():
            with self.subTest(language=language):
                self.assertEqual(set(catalog), reference)

    def test_native_translations_preserve_placeholders_and_valid_text(self):
        for language, catalog in self.catalogs.items():
            for key, value in catalog.items():
                with self.subTest(language=language, key=key):
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())
                    self.assertNotIn('\ufffd', value)
                    self.assertNotIn('\\(', value, 'Swift interpolation must use catalog placeholders')
                    self.assertEqual(Counter(PLACEHOLDER.findall(value)), Counter(PLACEHOLDER.findall(key)))
                    self.assertFalse(any(ord(char) < 32 and char not in '\n\t' for char in value))

    def test_every_explicit_native_lookup_exists(self):
        catalog = self.catalogs['en']
        lookups = []
        for path in NATIVE.glob('*.swift'):
            source = path.read_text()
            for match in re.finditer(r'\bL\s*\(\s*(?=")', source):
                key, _ = swift_literal(source, match.end())
                lookups.append((path.name, key))
        self.assertTrue(lookups, 'Expected native views to use catalog lookups')
        missing = [(name, key) for name, key in lookups if key not in catalog]
        self.assertEqual(missing, [], 'Explicit lookup missing from catalogs')

    def test_direct_visible_swiftui_literals_are_localized(self):
        # Brands, printed modifier glyphs, and numbers are intentionally invariant.
        allowed = {'AMG65', 'AMG65 Studio', 'STUDIO / MAC', 'Claude', 'Cursor', 'Codex'}
        problems = []
        call = re.compile(r'\b(?:Text|Button|Label|ColorPicker|Picker|Toggle|TextField|'
                          r'GroupBox|DisclosureGroup)\s*\(\s*(?=")')
        for path in NATIVE.glob('*.swift'):
            if path.name == 'Localization.swift':
                continue
            source = path.read_text()
            for match in call.finditer(source):
                value, _ = swift_literal(source, match.end())
                visible = PLACEHOLDER.sub('', value)
                if value not in allowed and any(char.isalpha() for char in visible):
                    line = source.count('\n', 0, match.start()) + 1
                    problems.append(f'{path.name}:{line}: {value}')
        self.assertEqual(problems, [], 'Wrap visible SwiftUI literals with L(...)')

    def test_shared_panel_and_slider_titles_have_catalog_entries(self):
        catalog = self.catalogs['en']
        missing = []
        for path in NATIVE.glob('*.swift'):
            source = path.read_text()
            for match in re.finditer(r'\b(?:Panel|ByteSlider)\s*\(\s*title\s*:\s*(?=")', source):
                key, _ = swift_literal(source, match.end())
                if key not in catalog:
                    missing.append((path.name, key))
        self.assertEqual(missing, [], 'Custom view titles must resolve through the catalog')

    def test_stored_visible_diagnostics_have_exact_or_template_entries(self):
        # These strings are deliberately stored in source language and translated
        # when presented. Checking only L("literal") would miss their error paths.
        patterns = [
            r'\b(?:message|error)\s*=\s*(?=")',
            r'\blines\s*:\s*\[\s*(?=")',
            r'\bfinish\(false,\s*\[\s*(?=")',
            r'\b(?:failure|usb)\(\s*(?=")',
            r'\blines\.append\(\s*(?=")',
        ]
        missing = []
        catalog = self.catalogs['en']
        for path in NATIVE.glob('*.swift'):
            source = path.read_text()
            for pattern in patterns:
                for match in re.finditer(pattern, source):
                    key, _ = swift_literal(source, match.end())
                    if key not in catalog:
                        missing.append((path.name, key))
        self.assertEqual(sorted(set(missing)), [], 'Visible stored diagnostics need catalog coverage')


class DashboardMarkup(HTMLParser):
    """Record authored text, including accessibility labels, without a browser."""
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.catalog_text = []
        self.scripts = []
        self.visible = []
        self.stack = []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag not in {'meta', 'link', 'input', 'br', 'hr', 'img', 'source'}:
            self.stack.append((tag, attrs))
        for name in ('aria-label', 'placeholder', 'title'):
            if attrs.get(name):
                self.visible.append((name, attrs[name]))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not self.stack:
            return
        tag, attrs = self.stack[-1]
        if tag == 'script':
            if attrs.get('id') == 'localization-catalog':
                self.catalog_text.append(data)
            elif attrs.get('type') in (None, 'text/javascript', 'application/javascript'):
                self.scripts.append(data)
        elif not any(name in {'script', 'style'} for name, _ in self.stack):
            if data.strip():
                self.visible.append((tag, data.strip()))


class WebLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.markup = DashboardMarkup((ROOT / 'dashboard.html').read_text())
        cls.catalogs = json.loads(''.join(cls.markup.catalog_text), object_pairs_hook=unique_object)

    def test_web_and_native_support_the_same_languages(self):
        self.assertEqual(set(self.catalogs), LOCALES)
        self.assertEqual(set(self.catalogs), {path.stem for path in CATALOGS.glob('*.json')})

    def test_web_catalog_keys_and_named_placeholders_match(self):
        reference = set(self.catalogs['tr'])
        self.assertTrue(reference)
        for language, catalog in self.catalogs.items():
            self.assertEqual(set(catalog), reference, language)
            for key, value in catalog.items():
                with self.subTest(language=language, key=key):
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())
                    self.assertNotIn('\ufffd', value)
                    self.assertEqual(Counter(WEB_PLACEHOLDER.findall(value)),
                                     Counter(WEB_PLACEHOLDER.findall(key)))

    def test_authored_web_text_and_accessible_labels_have_translations(self):
        invariant = {'AMG65', 'AMG65 Studio', 'STUDIO', 'Studio', 'STUDIO / MAC', 'USB', 'LED',
                     'Claude', 'Codex', 'Cursor', 'CodexBar', 'A', 'X', 'C',
                     'Türkçe', 'English', 'Español', '简体中文', '日本語',
                     'AMG65 STUDIO', 'LEOBOG / AMG65 Studio', '63 × 5 LED'}
        catalog = self.catalogs['tr']
        missing = []
        for kind, value in self.markup.visible:
            if value in invariant or not any(character.isalpha() for character in value):
                continue
            if re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                continue
            if value not in catalog:
                missing.append((kind, value))
        self.assertEqual(missing, [], 'Visible markup/accessible labels missing from web catalog')

    def test_explicit_dynamic_web_lookups_exist(self):
        source = '\n'.join(self.markup.scripts)
        literal = r'''(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")'''
        lookups = [ast.literal_eval(match.group(1)) for match in
                   re.finditer(r'\bt\(\s*(' + literal + ')', source)]
        self.assertTrue(lookups, 'Dynamic dashboard messages must use catalog lookups')
        self.assertEqual(sorted({key for key in lookups if key not in self.catalogs['tr']}), [])

    def javascript(self, names):
        """Extract the real named helpers; never execute the app's startup/poller."""
        source = '\n'.join(self.markup.scripts)
        functions = []
        for name in names:
            match = re.search(r'\bfunction ' + re.escape(name) + r'\([^)]*\)\s*\{', source)
            self.assertIsNotNone(match, f'Missing dashboard helper {name}')
            depth, end = 1, match.end()
            while depth:
                depth += (source[end] == '{') - (source[end] == '}')
                end += 1
            functions.append(source[match.start():end])
        return '\n'.join(functions)

    def run_javascript(self, script):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node is required only for offline JavaScript behavioral checks')
        result = subprocess.run([node, '-e', script], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fragment_language_validation_and_precedence(self):
        script = 'const assert=require("node:assert/strict");\n'
        script += 'const SUPPORTED_LANGUAGES=' + json.dumps(sorted(LOCALES)) + ';\n'
        script += self.javascript(['normalizeLanguage', 'resolveLanguage'])
        script += r'''
for (const code of SUPPORTED_LANGUAGES) {
  assert.equal(resolveLanguage('#native&lang='+code,'tr'),code);
  assert.equal(resolveLanguage('#lang='+code+'&native','en'),code);
  assert.equal(resolveLanguage('',code),code);
}
for (const invalid of [null,undefined,'','EN','en-US','zh','zh-Hant','fr','__proto__',
                       'constructor','../../en','en<script>']) {
  assert.equal(normalizeLanguage(invalid),null);
  assert.equal(resolveLanguage('#native&lang='+encodeURIComponent(String(invalid)),'ja'),'ja');
  assert.equal(resolveLanguage('',invalid),'tr');
}
assert.equal(resolveLanguage('#native&lang=%E6%97%A5%E6%9C%AC%E8%AA%9E',null),'tr');
assert.equal(resolveLanguage('#native&lang=zh-Hans','es'),'zh-Hans');
'''
        self.run_javascript(script)

    def test_language_change_preserves_drafts_pending_state_and_numeric_rendering(self):
        source = '\n'.join(self.markup.scripts)
        constants = []
        for name in ('valid', 'percent', 'date', 'time', 'activityKeys'):
            match = re.search(r'^\s*const ' + name + r' = .+$', source, re.MULTILINE)
            self.assertIsNotNone(match, name)
            constants.append(match.group(0))
        script = 'const assert=require("node:assert/strict");\n'
        script += 'const CATALOG=' + json.dumps(self.catalogs, ensure_ascii=False) + ';\n'
        script += 'const SUPPORTED_LANGUAGES=' + json.dumps(sorted(LOCALES)) + ';\n'
        script += r'''
let locale='tr',nativeOwner=false,displayEnabled=false;
const definitions=[{id:'claude',label:'Claude'},{id:'codex',label:'Codex'},{id:'cursor',label:'Cursor'}];
class Element {
  constructor(){this.textContent='';this.value='';this.style={};this.dataset={};this.nodes={};
    this.attributes={};this.options=[];this.classList={toggle(){},contains(){return false}};}
  querySelector(key){return this.nodes[key] ||= new Element();}
  setAttribute(key,value){this.attributes[key]=String(value);}
  removeAttribute(key){delete this.attributes[key];}
  replaceChildren(){}
  append(){}
}
const nodes={},$=id=>nodes[id] ||= new Element();
const elements=Object.fromEntries(definitions.map(def=>[def.id,new Element()]));
const pixels=Array.from({length:315},()=>new Element());
const document={documentElement:{lang:'tr'},createElement:()=>new Element()};
const saved=new Map();let storageUnavailable=false;
const localStorage={setItem(key,value){if(storageUnavailable)throw Error('storage disabled');saved.set(key,value)}};
const staticText=[{node:new Element(),key:'Genel bakış',before:' ',after:' '}];
const staticAttributes=[{node:new Element(),attr:'aria-label',key:'Saati eşitle'}];
const effects=['Kapalı','Sabit'];$('light-mode').options=[new Element(),new Element()];
const tabs=[{getAttribute:()=> 'true',dataset:{view:'lighting'}}];
function selectView(value){assert.equal(value,'lighting')}
function updateLightingPreview(){} function updateDisplayPreview(){} function clock(){}
function updateCommandDisabled(){}
function syncForms(){throw Error('language change must not resync forms')}
function renderOperation(){throw Error('language change must not consume operation state')}
function setOperation(){throw Error('no existing operation presentation in this fixture')}
function fetch(){throw Error('language change must not send a network request')}
const drafts={lighting:{dirty:true,submitted:{mode:2},revision:4},settings:{dirty:true,submitted:null,revision:3}};
const busy=true,awaitingOperation=true,operationBaseline='in-flight',refreshBaseline='unchanged';
const operationPresentation=null;
const lastStatus={settings:{display_mode:'text'},operation:{pending:true},running:true,
  device:{connected:true,code:'streaming'},
  providers:[{id:'claude',remaining_percent:54.39,remaining_label:'weekly',windows:[],stale:false},
             {id:'codex',remaining_percent:null,windows:[],stale:false},
             {id:'cursor',remaining_percent:0,windows:[],stale:false}],
  matrix:{pixels:Array.from({length:315},()=>[12,34,56])}};
$('custom-text').value='MY UNSAVED TEXT';$('light-color').value='#123456';
const before=JSON.stringify({drafts,busy,awaitingOperation,operationBaseline,refreshBaseline,
  text:$('custom-text').value,color:$('light-color').value,lastStatus});
'''
        script += '\n'.join(constants) + '\n'
        script += self.javascript(['normalizeLanguage', 't', 'formattedPercent', 'unit',
                                   'windowLabel', 'relative', 'age', 'deviceText',
                                   'operationOf', 'renderActivity', 'render', 'applyLanguage'])
        script += r'''
for (const code of SUPPORTED_LANGUAGES) {
  applyLanguage(code);
  assert.equal(document.documentElement.lang,code);
  assert.equal(saved.get('amg65-studio.language'),code);
  assert.equal($('language-picker').value,code);
  assert.equal(staticText[0].node.textContent,' '+CATALOG[code]['Genel bakış']+' ');
  assert.equal(staticAttributes[0].node.attributes['aria-label'],CATALOG[code]['Saati eşitle']);
  assert.equal(elements.claude.querySelector('.meter-fill').style.width,'54.39%');
  assert.equal(elements.claude.querySelector('.meter').attributes['aria-valuenow'],'54.39');
  assert.equal(elements.codex.querySelector('.allowance strong').textContent,'--');
  assert.equal(elements.cursor.querySelector('.meter-fill').style.width,'0%');
  assert.equal(pixels[0].attributes.fill,'rgb(12,34,56)');
  if(code==='es')assert.equal(elements.claude.querySelector('.allowance strong').textContent,'54,4');
  assert.equal(JSON.stringify({drafts,busy,awaitingOperation,operationBaseline,refreshBaseline,
    text:$('custom-text').value,color:$('light-color').value,lastStatus}),before);
}
storageUnavailable=true;applyLanguage('en');assert.equal(document.documentElement.lang,'en');
locale='en';assert.equal(t('Kaynak: {source}',{source:'{source} $1 \\ file'}),'Source: {source} $1 \\ file');
'''
        self.run_javascript(script)


if __name__ == '__main__':
    unittest.main()
