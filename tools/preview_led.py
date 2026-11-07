#!/usr/bin/env python3
"""Offline, synthetic LED previews using Studio's actual renderer.

SVG/HTML use only the standard library. PNG/GIF are optional and require Pillow in
the caller's environment; Pillow is not a Studio runtime dependency. No device,
account, settings, cache, network or provider authentication is accessed.

Example: python3 tools/preview_led.py --html /tmp/led.html --png /tmp/led.png
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import html
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from renderer import (ACTIVITY_LABELS, COLORS, HEIGHT, WIDTH, activity_label, apply_text_effect, render_activity,
                      render_claude_mascot, render_mascot, render_detail, render_overview, render_text, text_width)

SNAPSHOT = {'providers': [
    {'id':'claude', 'remaining_percent':98, 'stale':False},
    {'id':'codex', 'remaining_percent':46, 'stale':False},
    {'id':'cursor', 'remaining_percent':54, 'stale':False},
]}
NAMES = {'claude':'Claude', 'codex':'Codex', 'cursor':'Cursor'}
STATES = {'running':'Çalışıyor', 'queued':'Sırada', 'waiting_approval':'Onay bekliyor',
          'waiting_input':'Bilgi bekliyor', 'completed':'Tamamlandı', 'error':'Hata'}
EFFECT_STEPS = {'scan':64, 'breathe':12, 'matrix':11, 'scroll':64}  # Complete 2 Hz cycles.
ATTENTION_STATES = {'waiting_approval','waiting_input','error'}
EXAMPLE_TEXT = 'AMG65 STUDIO'
MASCOT_STEPS = 12
WORK_STEPS = {
    'working':('RUN','Çalışıyor'),
    'searching':('FIND','Arama yapıyor'),
    'reading_files':('READ','Dosya okuyor'),
    'editing_files':('EDIT','Dosya düzenliyor'),
    'running_command':('EXEC','Komut çalıştırıyor'),
    'using_tool':('TOOL','Araç kullanıyor'),
    'compacting':('CTX','Bağlamı düzenliyor'),
    'input_received':('READY','Bilgi alındı'),
}


def fixtures():
    """Produce every displayed RGB value through the production renderer."""
    frames = {'overview': [render_overview(SNAPSHOT, 1)]}
    for row in SNAPSHOT['providers']:
        provider = row['id']
        frames['detail:'+provider] = [render_detail(row, 1)]
        for state in STATES:
            times = (0, .5, 1, 1.5) if state == 'running' else (0,)
            frames['activity:'+provider+':'+state] = [
                render_activity({'provider':provider, 'state':state}, SNAPSHOT, 1, elapsed)
                for elapsed in times]
    unknown = deepcopy(SNAPSHOT)
    unknown['providers'][0]['remaining_percent'] = None
    stale = deepcopy(SNAPSHOT)
    stale['providers'][0]['stale'] = True
    frames['unknown'] = [render_overview(unknown, 1)]
    frames['stale'] = [render_overview(stale, 1)]
    frames['text'] = [render_text(EXAMPLE_TEXT, '#7bdcb0', 1)]
    for key, sequence in list(frames.items()):
        activity=key.startswith('activity:')
        if activity and key.rsplit(':',1)[1] in ATTENTION_STATES:
            continue
        for effect in EFFECT_STEPS:
            if key=='text' and effect=='scroll':
                # The text renderer repeats the full phrase; applying a second
                # image-scroll layer would double the movement and clip letters.
                frames['effect:scroll:text'] = [
                    render_text(EXAMPLE_TEXT, '#7bdcb0', 1, phase*.5, marquee=True)
                    for phase in range(text_width(EXAMPLE_TEXT)+10)]
                continue
            period=57 if effect=='scroll' and activity else EFFECT_STEPS[effect]
            frames['effect:'+effect+':'+key] = [
                apply_text_effect(sequence[phase%len(sequence)], effect, 1, phase*.5,
                                  left=7 if activity else 0)
                for phase in range(math.lcm(period,len(sequence)))]
    # Each provider has its own original Studio sprite; no effect layering.
    for provider in NAMES:
        for state in STATES:
            frames['mascot:'+provider+':'+state] = [
                render_mascot({'provider':provider,'state':state}, SNAPSHOT, 1, phase*.5)
                for phase in range(MASCOT_STEPS if state=='running' else 2 if state=='completed' else 1)]
    # Preserve earlier Claude-only export flags and fixture references.
    for state in STATES:
        frames['mascot:'+state]=frames['mascot:claude:'+state]
    for summary in WORK_STEPS:
        for provider in NAMES:
            frames['step:activity:'+provider+':'+summary] = [
                render_activity({'provider':provider,'state':'running','summary':summary}, SNAPSHOT, 1, phase*.5)
                for phase in range(4)]
        frames['step:mascot:'+summary] = [
            render_claude_mascot({'provider':'claude','state':'running','summary':summary}, SNAPSHOT, 1, phase*.5)
            for phase in range(MASCOT_STEPS)]
    for sequence in frames.values():
        for frame in sequence:
            if len(frame) != WIDTH*HEIGHT or any(len(pixel)!=3 or any(not isinstance(v,int) or not 0<=v<=254 for v in pixel) for pixel in frame):
                raise ValueError('Renderer returned an invalid RGB frame')
    return frames


MASCOT_ROWS = [('mascot:'+state,'Claude maskotu · '+ACTIVITY_LABELS[state],label,
               'İleri geri yürüyüş' if state=='running' else 'İki karelik sevinç pozu' if state=='completed' else 'Duruma özel sabit poz')
              for state,label in STATES.items()]
PRODUCT_MASCOT_ROWS = [('mascot:'+provider+':'+state,NAMES[provider]+' maskotu · '+ACTIVITY_LABELS[state],label,
                       'Sağlayıcıya özel Studio piksel karakteri')
                      for provider in NAMES for state,label in STATES.items()]

ROWS = [
    ('overview','Genel görünüm','A · Claude / X · Codex / C · Cursor','Kalan haklar: %98 / %46 / %54'),
    ('detail:claude','Claude detayı','Sağdaki blok: seçili kota','Tam ad + kalan yüzde'),
    ('activity:claude:running','Claude · RUN','Çalışıyor','Hareket yalnızca soldaki simgede'),
    ('activity:claude:waiting_approval','Claude · ASK','Onay bekliyor','Sabit uyarı simgesi'),
    ('activity:claude:waiting_input','Claude · INPUT','Bilgi bekliyor','Sabit soru simgesi'),
    ('activity:codex:running','Codex · RUN','Çalışıyor','Üç kota göstergesi görünür kalır'),
    ('activity:cursor:completed','Cursor · DONE','Tamamlandı','Onay işareti + durum kodu'),
    ('activity:claude:queued','Claude · QUEUE','Sırada','Sabit bekleme simgesi'),
    ('activity:claude:error','Claude · ERROR','Hata','Kırmızı hata simgesi'),
    ('unknown','Bilinmeyen kota','Claude verisi yok: --','Sıfır olarak gösterilmez'),
    ('stale','Eski kota verisi','Claude değeri soluk + sarı işaret','Diğer sağlayıcılar güncel örnektir'),
    ('text','Kişisel metin','AMG65 STUDIO','Sağdaki T: metin modu'),
    ('effect:scan:text','Tarama · SCAN','Metnin üzerinde ışık geçişi','Yalnızca yanan pikseller değişir'),
    ('effect:breathe:text','Nefes · BREATHE','Hafif parlaklık döngüsü','Harfler yerinde ve okunur kalır'),
    ('effect:matrix:text','Matrix · metin','Harfler aşağı akar','Okuma arası + sabit sağ gösterge'),
    ('effect:matrix:activity:claude:running','Matrix · Claude RUN','Ad ve durum harfleri aşağı akar','Sol iş simgesi + kota göstergeleri korunur'),
    ('effect:scroll:text','Kayan yazı · metin','Kısa metin de sola doğru akar','Tüm ifade boşlukla tekrarlanır'),
    ('effect:scroll:activity:codex:running','Kayan yazı · Codex RUN','Ad ve durum sola doğru kayar','Sol iş simgesi + kota göstergeleri korunur'),
] + PRODUCT_MASCOT_ROWS + [
    ('step:activity:codex:running_command','Codex · EXEC','Komut çalıştırıyor','Örnek adım; komut içeriği gösterilmez'),
    ('step:mascot:reading_files','Claude maskotu · READ','Dosya okuyor','Örnek adım; dosya adı gösterilmez'),
    ('step:mascot:editing_files','Claude maskotu · EDIT','Dosya düzenliyor','Örnek adım; dosya içeriği gösterilmez'),
    ('step:activity:cursor:searching','Cursor · FIND','Arama yapıyor','Örnek adım; arama metni gösterilmez'),
]

SHEET_WIDTH, SHEET_HEIGHT = 1240, 340+len(ROWS)*130
PANEL_X, PANEL_WIDTH, PITCH = 343, 845, 12.8


def sheet_frame(frames, key):
    sequence=frames[key]
    return sequence[2 if key.startswith('effect:matrix:') else 6 if key.startswith('effect:') else 0]


def svg_sheet(frames):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{SHEET_WIDTH}" height="{SHEET_HEIGHT}" viewBox="0 0 {SHEET_WIDTH} {SHEET_HEIGHT}" role="img" aria-labelledby="title desc">',
        '<title id="title">AMG65 Studio LED düzenleri — sentetik örnek veriler</title>',
        '<desc id="desc">Gerçek 63 × 5 renderer ile genel görünüm, kota detayı, iş durumları, bilinmeyen ve eski veri ile metin örnekleri. Fiziksel LED renk ölçümü değildir.</desc>',
        '<rect width="100%" height="100%" fill="#090f16"/>',
        '<g font-family="-apple-system,BlinkMacSystemFont,Arial,sans-serif">',
        '<text x="52" y="54" font-size="13" letter-spacing="3" fill="#8da3b5">AMG65 STUDIO / TASARIM ÖNİZLEMESİ</text>',
        '<text x="50" y="113" font-size="43" font-weight="700" fill="#f3f7fc">63 × 5. Her pikselin bir işi var.</text>',
        '<text x="52" y="150" font-size="16" fill="#afbdcc">ÖRNEK VERİ · Claude %98 · Codex %46 · Cursor %54 · Parlaklık %100</text>']
    for index, (key,title,subtitle,note) in enumerate(ROWS):
        y = 183 + index*130
        parts.extend([
            f'<rect x="36" y="{y}" width="1168" height="116" rx="16" fill="#101a25" stroke="#223141"/>',
            f'<text x="56" y="{y+31}" font-size="18" font-weight="600" fill="#edf3f9">{html.escape(title)}</text>',
            f'<text x="56" y="{y+59}" font-size="12" fill="#a9baca">{html.escape(subtitle)}</text>',
            f'<text x="56" y="{y+80}" font-size="11" fill="#7f94a7">{html.escape(note)}</text>',
            f'<rect x="{PANEL_X}" y="{y+16}" width="{PANEL_WIDTH}" height="84" rx="12" fill="#070c12" stroke="#263748"/>'])
        frame = sheet_frame(frames,key)
        for p, rgb in enumerate(frame):
            x = PANEL_X+24+(p%WIDTH)*PITCH
            cy = y+32+(p//WIDTH)*PITCH
            color = f'rgb({rgb[0]},{rgb[1]},{rgb[2]})' if any(rgb) else '#1a2531'
            parts.append(f'<circle cx="{x:.1f}" cy="{cy:.1f}" r="4.1" fill="{color}"/>')
    bottom=SHEET_HEIGHT-126
    parts.extend([
        f'<path d="M52 {bottom}H1188" stroke="#293746"/>',
        f'<text x="52" y="{bottom+32}" font-size="14" fill="#c7d7e6">Aktivite düzeni: 5 px simge → x7 ad → x32 durum → x57 / 59 / 61 kota göstergeleri</text>',
        f'<text x="52" y="{bottom+63}" font-size="12" fill="#8da3b5">Tüm kareler uygulamanın gerçek renderer.py işlevleriyle üretildi. Değerler tamamen sentetiktir.</text>',
        f'<text x="52" y="{bottom+87}" font-size="12" fill="#8da3b5">Bu görsel fiziksel LED renk/parlaklık ölçümü değildir. Gerçek cihazın optiği farklı görünebilir.</text>',
        '</g></svg>'])
    return '\n'.join(parts)


HTML_TEMPLATE = r'''<!doctype html>
<html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>AMG65 Studio · LED önizlemesi</title>
<style>
:root{color-scheme:dark;--bg:#090f16;--panel:#111c28;--line:#263747;--muted:#94a9bd;--text:#edf5fc;--mint:#7bdcb0;--orange:__CLAUDE_COLOR__;--blue:#86bef8}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 85% 0,#152b30 0,transparent 44%),var(--bg);color:var(--text);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1240px;margin:0 auto;padding:48px 28px 40px}.eyebrow{font-size:11px;letter-spacing:.22em;color:var(--mint);font-weight:650}h1{font-size:clamp(30px,4vw,49px);line-height:1.12;letter-spacing:-.045em;margin:17px 0}p{color:var(--muted);max-width:850px}.badge{display:inline-flex;align-items:center;gap:8px;padding:7px 11px;border:1px solid #345047;border-radius:30px;font-size:11px;color:#a1e5c5;background:#14271f}.badge:before{content:"";width:6px;height:6px;background:var(--mint);border-radius:50%}.topline{display:flex;align-items:center;justify-content:space-between;gap:15px}.console{margin-top:30px;background:linear-gradient(135deg,#152230,#101923);border:1px solid var(--line);border-radius:24px;padding:24px;box-shadow:0 24px 80px #0005}.console-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;gap:16px}.console-head strong{font-size:17px}.pill{border:1px solid #3a4b5b;border-radius:30px;padding:5px 10px;color:#b4c4d4;font-size:11px}.matrix-frame{padding:22px 20px;background:#05090e;border:1px solid #304152;border-radius:15px;box-shadow:inset 0 2px 7px #0008;overflow:hidden}svg.matrix{width:100%;height:auto;display:block;overflow:visible}.rails{display:flex;justify-content:space-between;color:#71879b;font:10px/1.3 ui-monospace,monospace;margin:14px 2px 0}.controls{display:grid;grid-template-columns:1.15fr .9fr 1.1fr 1fr 1.3fr;gap:16px;margin-top:26px}label{display:block;font-size:11px;color:#a9bfd1;letter-spacing:.04em}select,button{font:inherit;color:var(--text);background:#0d1722;border:1px solid #33485d;border-radius:9px;min-height:42px;padding:9px 12px}select{width:100%;margin-top:7px;font-size:13px}select:disabled{opacity:.4}select:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid var(--mint);outline-offset:3px}button{cursor:pointer;font-size:12px;min-height:34px}button:hover{background:#1a2c3b}input[type=range]{width:100%;margin:20px 0 0;accent-color:var(--mint)}.range-label{display:flex;justify-content:space-between}.range-label output{color:var(--mint);font-variant-numeric:tabular-nums}.context{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-top:21px;padding-top:17px;border-top:1px solid #273747;color:#99afc2;font-size:12px}.context p{margin:0}.legend{display:flex;flex-wrap:wrap;gap:10px;margin:25px 0 34px}.legend span{padding:7px 12px;border:1px solid var(--line);background:#0e1822;border-radius:8px;font-size:12px}.legend b{font-variant-numeric:tabular-nums;font-weight:600;margin-left:12px;color:#e8f0f9}.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:7px}.section-head{display:flex;justify-content:space-between;gap:20px;align-items:center}.section-head h2{font-size:21px;letter-spacing:-.02em;margin:4px 0}.section-head small{font-size:11px;color:var(--muted)}.gallery{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:17px}.tile{padding:18px;background:#0f1924;border:1px solid #233544;border-radius:14px}.tile-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:15px}.tile strong{font-size:13px}.tile small{font-size:10px;color:#8fa6ba}.tile .matrix-frame{padding:12px 10px;border-radius:9px}.tile p{font-size:11px;margin:12px 0 0}.foot{font-size:11px;color:#8096aa;border-top:1px solid var(--line);margin-top:30px;padding-top:22px}.note{color:#bdcbd8}a{color:var(--mint)}@media(max-width:850px){.controls{grid-template-columns:1fr 1fr}.gallery{grid-template-columns:1fr}.topline{align-items:flex-start}.badge{font-size:10px}.console{padding:18px}}@media(max-width:500px){main{padding:28px 16px}.controls{gap:12px}.matrix-frame{padding:13px 10px}.rails{font-size:8px}.context{align-items:flex-start}.topline{flex-direction:column}.console-head strong{font-size:14px}.pill{font-size:9px}.section-head{align-items:flex-start;flex-direction:column;gap:4px}}
</style>
<main>
<div class="topline"><div class="eyebrow">AMG65 STUDIO / 63 × 5 LED</div><span class="badge">Çevrimdışı · yalnızca örnek veri</span></div>
<h1>Klavyenin küçük ekranı.<br>Bir bakışta büyük resim.</h1>
<p>Kotalar ve iş durumları, uygulamanın gerçek çizim koduyla. Sağlayıcıyı, durumu ve parlaklığı seçin; tüm düzenleri aynı panelde karşılaştırın.</p>
<section class="console" aria-label="Etkileşimli LED önizlemesi">
 <div class="console-head"><strong id="view-title">Genel görünüm</strong><span class="pill">63 sütun · 5 satır · 315 RGB piksel</span></div>
 <div class="matrix-frame"><svg class="matrix" id="preview" viewBox="0 0 756 60" role="img" aria-labelledby="view-title preview-description"><desc id="preview-description">Sentetik Claude yüzde98, Codex yüzde46 ve Cursor yüzde54 kalan kota.</desc></svg></div>
 <div class="rails"><span id="layout-label">A / CLAUDE &nbsp; X / CODEX &nbsp; C / CURSOR</span><span>SAĞ: A · X · C</span></div>
 <div class="controls">
  <label>Görünüm<select id="mode"><option value="overview">Tüm kotalar</option><option value="detail">Sağlayıcı detayı</option><option value="activity">İş durumu</option><option value="mascot">Sağlayıcı maskotu</option><option value="unknown">Bilinmeyen kota</option><option value="stale">Eski kota verisi</option><option value="text">Kişisel metin</option></select></label>
  <label>Sağlayıcı<select id="provider"><option value="claude">Claude</option><option value="codex">Codex</option><option value="cursor">Cursor</option></select></label>
  <label>İş durumu<select id="state"><option value="running">RUN · Çalışıyor</option><option value="queued">QUEUE · Sırada</option><option value="waiting_approval">ASK · Onay bekliyor</option><option value="waiting_input">INPUT · Bilgi bekliyor</option><option value="completed">DONE · Tamamlandı</option><option value="error">ERROR · Hata</option></select></label>
  <label>Metin efekti<select id="effect"><option value="none">Sade · efekt yok</option><option value="scan">Tarama</option><option value="breathe">Nefes</option><option value="matrix">Matrix</option><option value="scroll">Kayan yazı</option></select></label>
  <label><span class="range-label">Önizleme parlaklığı <output id="brightness-label" for="brightness">%75</output></span><input id="brightness" type="range" min="0" max="100" step="1" value="75" aria-label="Önizleme parlaklığı"></label>
 </div>
 <div class="context"><p id="explanation">Üç sağlayıcının kalan hakları aynı anda görünür.</p><button id="motion" type="button" aria-pressed="true">Hareket: açık</button></div>
</section>
<div class="legend" aria-label="Sentetik kalan haklar"><span><i class="dot" style="background:var(--orange)"></i>A · Claude<b>%98</b></span><span><i class="dot" style="background:var(--mint)"></i>X · Codex<b>%46</b></span><span><i class="dot" style="background:var(--blue)"></i>C · Cursor<b>%54</b></span></div>
<div class="section-head"><h2>Düzen kataloğu</h2><small>Gerçek renderer kareleri · katalog parlaklığı %100</small></div>
<div class="gallery" id="gallery"></div>
<p class="foot"><span class="note">Değerlerin tamamı sentetik örnektir; gerçek hesap veya kullanım bilgisi değildir.</span><br>Bu dosya ağ isteği yapmaz, klavyeye bağlanmaz ve ayar değiştirmez. Parlaklık kaydırıcısı önceden üretilmiş RGB değerlerini doğrusal ölçekler. Fiziksel LED renk/parlaklık ölçümü değildir; gerçek cihazın optiği ve ekranınızın renk işleme biçimi farklı görünebilir. Sade modda RUN simgesi hareket eder. Metin efektleri RUN/QUEUE/DONE ekranlarında ad ve duruma uygulanır; sol simge ile sağ kota göstergeleri korunur. ASK/INPUT/ERROR ekranları sabit kalır. Her sağlayıcının ayrı bir Studio piksel karakteri vardır. Maskot sahnelerine metin efektleri uygulanmaz.</p>
</main>
<script type="application/json" id="frame-data">__DATA__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('frame-data').textContent),NS='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id);let phase=0,animate=true;
function matrix(svg,frame,brightness=1){
 const desc=svg.querySelector('desc');svg.replaceChildren();if(desc)svg.append(desc);
 frame.forEach((rgb,index)=>{const node=document.createElementNS(NS,'circle');node.setAttribute('cx',String(6+(index%63)*12));node.setAttribute('cy',String(6+Math.floor(index/63)*12));node.setAttribute('r','3.8');const value=rgb.map(v=>Math.round(v*brightness));node.setAttribute('fill',value.some(Boolean)?`rgb(${value.join(',')})`:'#18232f');svg.append(node);});
}
function effectProtected(){return $('mode').value==='mascot'||$('mode').value==='activity'&&['waiting_approval','waiting_input','error'].includes($('state').value);}
function key(){const mode=$('mode').value;if(mode==='mascot')return `mascot:${$('provider').value}:${$('state').value}`;const base=mode==='activity'?`activity:${$('provider').value}:${$('state').value}`:mode==='detail'?`detail:${$('provider').value}`:mode;return !effectProtected()&&$('effect').value!=='none'?`effect:${$('effect').value}:${base}`:base;}
const explanations={mascot:'Seçilen sağlayıcının Studio piksel karakteri çalışırken hareket eder. Diğer durumlarda ilgili poz gösterilir; kota göstergeleri korunur.',overview:'Üç sağlayıcının kalan hakları aynı anda görünür.',detail:'Seçilen sağlayıcının tam adı, kalan yüzdesi ve sağda tek kota bloğu.',activity:'5 px simge → sağlayıcı adı → durum kodu. Sağdaki üç kota göstergesi sabit kalır.',unknown:'Claude kotası bilinmiyor: -- ve orta nokta. Bilinmeyen değer sıfıra çevrilmez.',stale:'Claude kotası eski: değer soluk, hücre sonunda sarı işaret. Diğer iki kota güncel örnektir.',text:'Sağdaki T simgesi metin modunu belirtir. Kayan yazı seçeneği kısa metinleri de hareket ettirir.'};
const effectNotes={none:'',scan:' Tarama yalnızca yanan piksellerin parlaklığını değiştirir.',breathe:' Nefes efekti parlaklığı hafifçe değiştirir.',matrix:' Harfler gruplar halinde aşağı akar; her dalganın ardından okuma arası verilir.',scroll:' Kısa metinler de sola doğru akar; ifade boşlukla tekrarlanır.'};
const titles={mascot:'Sağlayıcı maskotu',overview:'Genel görünüm',detail:'Sağlayıcı detayı',activity:'İş durumu',unknown:'Bilinmeyen kota',stale:'Eski kota verisi',text:'Kişisel metin'};
function render(){const mode=$('mode').value;const sequence=data.frames[key()],brightness=Number($('brightness').value)/100;matrix($('preview'),sequence[(animate?phase:0)%sequence.length],brightness);$('brightness-label').textContent='%'+$('brightness').value;$('provider').disabled=!['activity','detail','mascot'].includes(mode);$('state').disabled=!['activity','mascot'].includes(mode);$('effect').disabled=effectProtected();$('explanation').textContent=explanations[mode]+(mode==='mascot'?' Maskot sahnesine metin efekti uygulanmaz.':effectProtected()?' Onay, bilgi bekleme ve hata durumları okunabilirlik için sabit kalır.':effectNotes[$('effect').value]);$('view-title').textContent=mode==='mascot'?data.names[$('provider').value]+' maskotu · '+data.labels[$('state').value]:mode==='activity'?data.names[$('provider').value]+' · '+data.labels[$('state').value]:mode==='detail'?data.names[$('provider').value]+' · kota detayı':titles[mode];$('layout-label').textContent=mode==='mascot'?'SAHNE 0–24 · A/X/C 26–28 · DURUM 32–52':mode==='activity'?'SİMGE 0–4 · AD 7–29 · DURUM 32–52':'A / CLAUDE · X / CODEX · C / CURSOR';$('preview-description').textContent=$('view-title').textContent+'. '+explanations[mode]+' Tamamen sentetik örnek veriler.';}
for(const id of ['mode','provider','state','effect','brightness'])$(id).addEventListener('input',render);
$('motion').addEventListener('click',()=>{animate=!animate;$('motion').setAttribute('aria-pressed',String(animate));$('motion').textContent=animate?'Hareket: açık':'Hareket: kapalı';render();});
for(const [k,title,subtitle,note] of data.rows){const card=document.createElement('article');card.className='tile';const head=document.createElement('div');head.className='tile-head';const strong=document.createElement('strong');strong.textContent=title;const small=document.createElement('small');small.textContent='63 × 5';head.append(strong,small);const frame=document.createElement('div');frame.className='matrix-frame';const svg=document.createElementNS(NS,'svg');svg.classList.add('matrix');svg.setAttribute('viewBox','0 0 756 60');svg.setAttribute('role','img');svg.setAttribute('aria-label',title+' — sentetik örnek');matrix(svg,data.frames[k][k.startsWith('effect:matrix:')?2:k.startsWith('effect:')?6:0]);frame.append(svg);const caption=document.createElement('p');caption.textContent=subtitle+' · '+note;card.append(head,frame,caption);$('gallery').append(card);}
if(matchMedia('(prefers-reduced-motion: reduce)').matches){animate=false;$('motion').textContent='Hareket: kapalı';$('motion').setAttribute('aria-pressed','false');}
render();setInterval(()=>{if(animate&&document.visibilityState==='visible'&&((['activity','mascot'].includes($('mode').value)&&$('state').value==='running')||($('mode').value==='mascot'&&$('state').value==='completed')||(!effectProtected()&&$('effect').value!=='none'))){phase+=1;render();}},500);
</script></html>'''


def html_preview(frames):
    payload = json.dumps({'frames':frames,'rows':ROWS,'names':NAMES,'labels':ACTIVITY_LABELS}, ensure_ascii=False, separators=(',',':'))
    return HTML_TEMPLATE.replace('__DATA__', payload.replace('<','\\u003c')).replace(
        '__CLAUDE_COLOR__','#'+''.join(f'{channel:02x}' for channel in COLORS['claude']))


def png_sheet(frames, path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise SystemExit('PNG export needs optional Pillow; SVG and HTML need only Python stdlib.') from error
    image = Image.new('RGB', (SHEET_WIDTH,SHEET_HEIGHT), '#090f16')
    draw = ImageDraw.Draw(image)
    font_paths = [Path('/System/Library/Fonts/Supplemental/Arial.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    chosen = next((p for p in font_paths if p.is_file()), None)
    def font(size):
        return ImageFont.truetype(str(chosen),size) if chosen else ImageFont.load_default(size=size)
    def text(x,y,value,size=14,color='#edf3f9'):
        draw.text((x,y),value,font=font(size),fill=color,anchor='ls')
    text(52,54,'AMG65 STUDIO / TASARIM ÖNİZLEMESİ',13,'#8da3b5')
    text(50,113,'63 × 5. Her pikselin bir işi var.',43)
    text(52,150,'ÖRNEK VERİ · Claude %98 · Codex %46 · Cursor %54 · Parlaklık %100',16,'#afbdcc')
    for index,(key,title,subtitle,note) in enumerate(ROWS):
        y=183+index*130
        draw.rounded_rectangle((36,y,1204,y+116),16,fill='#101a25',outline='#223141')
        text(56,y+31,title,18);text(56,y+59,subtitle,12,'#a9baca');text(56,y+80,note,11,'#7f94a7')
        draw.rounded_rectangle((PANEL_X,y+16,PANEL_X+PANEL_WIDTH,y+100),12,fill='#070c12',outline='#263748')
        for p,rgb in enumerate(sheet_frame(frames,key)):
            x=PANEL_X+24+(p%WIDTH)*PITCH;cy=y+32+(p//WIDTH)*PITCH
            draw.ellipse((x-4.1,cy-4.1,x+4.1,cy+4.1),fill=tuple(rgb) if any(rgb) else '#1a2531')
    bottom=SHEET_HEIGHT-126
    draw.line((52,bottom,1188,bottom),fill='#293746')
    text(52,bottom+32,'Aktivite düzeni: 5 px simge → x7 ad → x32 durum → x57 / 59 / 61 kota göstergeleri',14,'#c7d7e6')
    text(52,bottom+63,'Tüm kareler uygulamanın gerçek renderer.py işlevleriyle üretildi. Değerler tamamen sentetiktir.',12,'#8da3b5')
    text(52,bottom+87,'Bu görsel fiziksel LED renk/parlaklık ölçümü değildir. Gerçek cihazın optiği farklı görünebilir.',12,'#8da3b5')
    image.save(path, 'PNG', optimize=True)


def gif_matrix(frames, path, effect='matrix'):
    """Compact 2 Hz animation of an actual Matrix or marquee text cycle."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise SystemExit('GIF export needs optional Pillow; SVG and HTML need only Python stdlib.') from error
    font_path=next((p for p in (Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
                               Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')) if p.is_file()),None)
    def font(size):
        return ImageFont.truetype(str(font_path),size) if font_path else ImageFont.load_default(size=size)
    images=[]
    for phase,frame in enumerate(frames['effect:'+effect+':text']):
        image=Image.new('RGB',(960,236),'#090f16');draw=ImageDraw.Draw(image)
        title='MATRIX · HARFLER AŞAĞI AKAR' if effect=='matrix' else 'KAYAN YAZI · KISA METİN DE AKAR'
        draw.text((28,22),title,font=font(23),fill='#edf5fc')
        draw.text((28,57),'AMG65 STUDIO  /  63 × 5  /  GERÇEK RENDERER',font=font(11),fill='#94a9bd')
        draw.rounded_rectangle((24,87,936,182),12,fill='#05090e',outline='#304152')
        for index,rgb in enumerate(frame):
            x=46+(index%WIDTH)*14;y=107+(index//WIDTH)*14
            draw.ellipse((x-4.5,y-4.5,x+4.5,y+4.5),fill=tuple(rgb) if any(rgb) else '#18232f')
        state=('OKUMA ARASI' if phase>=7 else 'HARF AKIŞI') if effect=='matrix' else 'SOLA KAYIYOR'
        draw.text((28,204),'ÖRNEK METİN · 2 KARE/SN · FİZİKSEL RENK ÖLÇÜMÜ DEĞİLDİR',font=font(11),fill='#94a9bd')
        draw.text((931,204),state,font=font(11),fill='#7bdcb0',anchor='ra')
        images.append(image)
    images[0].save(path,'GIF',save_all=True,append_images=images[1:],duration=500,loop=0,disposal=2,optimize=True)


def mascot_artifacts(frames, png_path=None, gif_path=None):
    """Draw the production sprite at two scales, plus its full walking cycle."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise SystemExit('Mascot PNG/GIF export needs optional Pillow.') from error
    font_path=next((p for p in (Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
                               Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')) if p.is_file()),None)
    def font(size):
        return ImageFont.truetype(str(font_path),size) if font_path else ImageFont.load_default(size=size)
    def pixels(draw,frame,x,y,pitch,radius,width=63):
        for index,rgb in enumerate(frame):
            cx=x+(index%width)*pitch;cy=y+(index//width)*pitch
            draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),fill=tuple(rgb) if any(rgb) else '#18232f')
    if png_path:
        image=Image.new('RGB',(1240,1050),'#090f16');draw=ImageDraw.Draw(image)
        draw.text((40,28),'AMG65 STUDIO / CLAUDE MASKOTU',font=font(13),fill='#94a9bd')
        draw.text((40,62),'Altı durum. Tek küçük karakter.',font=font(34),fill='#edf5fc')
        draw.text((40,111),'11 × 5 piksel uyarlaması · Gerçek renderer kareleri · Örnek Claude %98 / Codex %46 / Cursor %54',font=font(14),fill='#a9bfd1')
        draw.text((272,145),'11 × 5 MASKOT',font=font(11),fill='#94a9bd')
        draw.text((456,145),'63 × 5 TAM SAHNE',font=font(11),fill='#94a9bd')
        for row,(key,title,label,note) in enumerate(MASCOT_ROWS):
            y=170+row*130;frame=frames[key][0]
            draw.rounded_rectangle((30,y,1210,y+116),15,fill='#101a25',outline='#263747')
            draw.text((48,y+21),'Claude · '+ACTIVITY_LABELS[key.split(':')[1]],font=font(19),fill='#edf5fc')
            draw.text((48,y+52),label,font=font(14),fill='#a9bfd1')
            draw.text((48,y+80),note,font=font(11),fill='#7f94a7')
            draw.rounded_rectangle((266,y+16,436,y+100),11,fill='#05090e',outline='#304152')
            visible=[x for x in range(25) if any(frame[yy*63+x]!=(0,0,0) for yy in range(5))]
            left=min(visible,default=0)
            sprite=[frame[yy*63+x] for yy in range(5) for x in range(left,left+11)]
            pixels(draw,sprite,283,y+32,13.6,4.6,11)
            draw.rounded_rectangle((451,y+16,1194,y+100),11,fill='#05090e',outline='#304152')
            pixels(draw,frame,468,y+34,11.4,3.8)
        draw.line((40,970,1200,970),fill='#293746')
        draw.text((40,990),'Sahne 0–24 · Claude kimliği A 26–28 · Durum 32–52 · Kota göstergeleri 57 / 59 / 61',font=font(13),fill='#b7c9d9')
        draw.text((40,1019),'Örnek veridir; fiziksel LED renk/parlaklık ölçümü değildir. Maskot sahnesine metin efekti uygulanmaz.',font=font(11),fill='#94a9bd')
        image.save(png_path,'PNG',optimize=True)
    if gif_path:
        images=[]
        for frame in frames['mascot:running']:
            image=Image.new('RGB',(960,236),'#090f16');draw=ImageDraw.Draw(image)
            draw.text((28,22),'CLAUDE · ÇALIŞIRKEN İLERİ GERİ YÜRÜR',font=font(23),fill='#edf5fc')
            draw.text((28,57),'11 × 5 MASKOT  /  63 × 5 TAM SAHNE  /  GERÇEK RENDERER',font=font(11),fill='#94a9bd')
            draw.rounded_rectangle((24,87,936,182),12,fill='#05090e',outline='#304152')
            pixels(draw,frame,46,107,14,4.5)
            draw.text((28,204),'ÖRNEK DURUM · 2 KARE/SN · FİZİKSEL RENK ÖLÇÜMÜ DEĞİLDİR',font=font(11),fill='#94a9bd')
            draw.text((931,204),'CLAUDE / RUN',font=font(11),fill=COLORS['claude'],anchor='ra')
            images.append(image)
        images[0].save(gif_path,'GIF',save_all=True,append_images=images[1:],duration=500,loop=0,disposal=2,optimize=True)


def gif_work_steps(frames, path):
    """Synthetic summary categories, never an inferred live task history."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise SystemExit('Work-step GIF export needs optional Pillow.') from error
    font_path=next((p for p in (Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
                               Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')) if p.is_file()),None)
    def font(size):
        return ImageFont.truetype(str(font_path),size) if font_path else ImageFont.load_default(size=size)
    images=[]
    for summary,(code,label) in WORK_STEPS.items():
        code=activity_label({'provider':'codex','state':'running','summary':summary})
        for frame in frames['step:activity:codex:'+summary]:
            image=Image.new('RGB',(960,236),'#090f16');draw=ImageDraw.Draw(image)
            draw.text((28,22),'CODEX · İŞ ADIMLARI',font=font(23),fill='#edf5fc')
            draw.text((28,57),'SENTETİK ADIM SIRASI  /  GERÇEK BİR GÖREV GEÇMİŞİ DEĞİLDİR',font=font(11),fill='#94a9bd')
            draw.rounded_rectangle((24,87,936,182),12,fill='#05090e',outline='#304152')
            for index,rgb in enumerate(frame):
                x=46+(index%WIDTH)*14;y=107+(index//WIDTH)*14
                draw.ellipse((x-4.5,y-4.5,x+4.5,y+4.5),fill=tuple(rgb) if any(rgb) else '#18232f')
            draw.text((28,204),label+' · komut, dosya adı veya içerik gösterilmez',font=font(12),fill='#94a9bd')
            draw.text((931,204),code,font=font(12),fill='#7bdcb0',anchor='ra')
            images.append(image)
    images[0].save(path,'GIF',save_all=True,append_images=images[1:],duration=500,loop=0,disposal=2,optimize=True)


def product_mascot_artifacts(frames, png_path=None, gif_path=None):
    """Compare three original Studio characters using only actual renderer data."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise SystemExit('Product mascot PNG/GIF export needs optional Pillow.') from error
    font_path=next((p for p in (Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
                               Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')) if p.is_file()),None)
    def font(size):
        return ImageFont.truetype(str(font_path),size) if font_path else ImageFont.load_default(size=size)
    def pixels(draw,frame,x,y,pitch,radius):
        for index,rgb in enumerate(frame):
            cx=x+(index%WIDTH)*pitch;cy=y+(index//WIDTH)*pitch
            draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),fill=tuple(rgb) if any(rgb) else '#18232f')
    characters={'claude':'Blok yengeç','codex':'Terminal robotu','cursor':'İmleç karakteri'}
    if png_path:
        image=Image.new('RGB',(1800,1100),'#090f16');draw=ImageDraw.Draw(image)
        draw.text((32,25),'AMG65 STUDIO / SAĞLAYICI MASKOTLARI',font=font(13),fill='#94a9bd')
        draw.text((32,58),'Üç sağlayıcı. Üç karakter.',font=font(39),fill='#edf5fc')
        draw.text((32,114),'Özgün Studio piksel uyarlamaları · Her hücre gerçek 63 × 5 renderer karesi · Veriler ve durumlar sentetiktir',font=font(16),fill='#a9bfd1')
        for column,(provider,name) in enumerate(NAMES.items()):
            x=140+550*column
            draw.text((x,161),name,font=font(29),fill=COLORS[provider])
            draw.text((x,199),characters[provider],font=font(13),fill='#94a9bd')
            for row,(state,label) in enumerate(STATES.items()):
                y=235+row*130
                if column==0:
                    draw.text((25,y+28),ACTIVITY_LABELS[state],font=font(21),fill='#edf5fc')
                    draw.text((25,y+60),label,font=font(11),fill='#94a9bd')
                draw.rounded_rectangle((x,y,x+520,y+99),13,fill='#101a25',outline='#263747')
                draw.rounded_rectangle((x+8,y+12,x+512,y+87),9,fill='#05090e',outline='#304152')
                pixels(draw,frames['mascot:'+provider+':'+state][0],x+17,y+33,7.85,2.7)
        draw.line((32,1020,1768,1020),fill='#293746')
        draw.text((32,1038),'A · Claude %98    X · Codex %46    C · Cursor %54     |     Sol sahne ve durum kodu değişir; üç kota göstergesi korunur.',font=font(14),fill='#b7c9d9')
        draw.text((32,1068),'Örnek veridir; fiziksel LED renk/parlaklık ölçümü değildir. Karakterler resmi sağlayıcı maskotu veya logosu olarak sunulmaz.',font=font(12),fill='#94a9bd')
        image.save(png_path,'PNG',optimize=True)
    if gif_path:
        images=[]
        for phase in range(MASCOT_STEPS):
            image=Image.new('RGB',(960,580),'#090f16');draw=ImageDraw.Draw(image)
            draw.text((28,20),'ÜÇ SAĞLAYICI · ÜÇ PİKSEL KARAKTER',font=font(26),fill='#edf5fc')
            draw.text((28,58),'ÖRNEK ÇALIŞMA DURUMLARI · GERÇEK RENDERER · 2 KARE/SN',font=font(12),fill='#94a9bd')
            for row,(provider,name) in enumerate(NAMES.items()):
                y=100+row*145
                draw.text((28,y),name+' · '+characters[provider],font=font(18),fill=COLORS[provider])
                draw.rounded_rectangle((24,y+33,936,y+117),12,fill='#05090e',outline='#304152')
                pixels(draw,frames['mascot:'+provider+':running'][phase],46,y+49,14,4.5)
            draw.text((28,550),'Sentetik örnekler · Özgün Studio karakterleri · Fiziksel renk ölçümü değildir',font=font(11),fill='#94a9bd')
            images.append(image)
        images[0].save(gif_path,'GIF',save_all=True,append_images=images[1:],duration=500,loop=0,disposal=2,optimize=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--svg',type=Path,default=ROOT/'docs/images/led-layouts.svg')
    parser.add_argument('--html',type=Path)
    parser.add_argument('--png',type=Path)
    parser.add_argument('--gif',type=Path)
    parser.add_argument('--scroll-gif',type=Path)
    parser.add_argument('--mascot-png',type=Path)
    parser.add_argument('--mascot-gif',type=Path)
    parser.add_argument('--steps-gif',type=Path)
    parser.add_argument('--product-mascots-png',type=Path)
    parser.add_argument('--product-mascots-gif',type=Path)
    args=parser.parse_args();frames=fixtures()
    args.svg.parent.mkdir(parents=True,exist_ok=True);args.svg.write_text(svg_sheet(frames),encoding='utf-8')
    print(args.svg)
    if args.html:
        args.html.parent.mkdir(parents=True,exist_ok=True);args.html.write_text(html_preview(frames),encoding='utf-8');print(args.html)
    if args.png:
        args.png.parent.mkdir(parents=True,exist_ok=True);png_sheet(frames,args.png);print(args.png)
    if args.gif:
        args.gif.parent.mkdir(parents=True,exist_ok=True);gif_matrix(frames,args.gif);print(args.gif)
    if args.scroll_gif:
        args.scroll_gif.parent.mkdir(parents=True,exist_ok=True);gif_matrix(frames,args.scroll_gif,'scroll');print(args.scroll_gif)
    if args.mascot_png or args.mascot_gif:
        for path in (args.mascot_png,args.mascot_gif):
            if path:path.parent.mkdir(parents=True,exist_ok=True)
        mascot_artifacts(frames,args.mascot_png,args.mascot_gif)
        for path in (args.mascot_png,args.mascot_gif):
            if path:print(path)
    if args.steps_gif:
        args.steps_gif.parent.mkdir(parents=True,exist_ok=True);gif_work_steps(frames,args.steps_gif);print(args.steps_gif)
    if args.product_mascots_png or args.product_mascots_gif:
        for path in (args.product_mascots_png,args.product_mascots_gif):
            if path:path.parent.mkdir(parents=True,exist_ok=True)
        product_mascot_artifacts(frames,args.product_mascots_png,args.product_mascots_gif)
        for path in (args.product_mascots_png,args.product_mascots_gif):
            if path:print(path)


if __name__=='__main__':
    main()
