"""Validated, bounded settings shared by the local API and device worker."""
import math
import re

DEFAULTS = {'display_mode':'overview','brightness':0.4,'text':'AMG65 STUDIO',
            'text_color':'#7bdcb0','text_effect':'none','activity_enabled':True}
LIGHTING = {'mode':1,'color':'#7bdcb0','brightness':3,'speed':3,'colorful':False}

def color(value):
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):
        raise ValueError('Geçerli bir #RRGGBB rengi gerekli.')
    return value.lower()

def settings_patch(value):
    if not isinstance(value,dict) or set(value)-DEFAULTS.keys():
        raise ValueError('Bilinmeyen ekran ayarı.')
    result = dict(value)
    if 'display_mode' in value and value['display_mode'] not in ('overview','rotate','text'):
        raise ValueError('Geçersiz ekran modu.')
    if 'text_effect' in value and value['text_effect'] not in ('none','scan','breathe','matrix'):
        raise ValueError('Geçersiz yazı efekti.')
    if 'brightness' in value:
        b=value['brightness']
        if type(b) not in (int,float) or not math.isfinite(b) or not 0<=b<=1:
            raise ValueError('Ekran parlaklığı 0 ile 1 arasında olmalı.')
    if 'activity_enabled' in value and type(value['activity_enabled']) is not bool:
        raise ValueError('activity_enabled bir boolean olmalı.')
    if 'text' in value:
        s=value['text']
        if not isinstance(s,str) or len(s)>64 or any(not 32<=ord(c)<=126 for c in s):
            raise ValueError('Metin en fazla 64 ASCII karakter olabilir.')
        result['text']=s.upper()
    if 'text_color' in value:
        result['text_color']=color(value['text_color'])
    return result

def lighting_request(value):
    if not isinstance(value,dict) or set(value)!=LIGHTING.keys():
        raise ValueError('Tüm aydınlatma alanları gerekli.')
    for key,lo,hi in [('mode',0,19),('brightness',1,5),('speed',1,5)]:
        if type(value[key]) is not int or not lo<=value[key]<=hi:
            raise ValueError(f'Geçersiz {key}.')
    if type(value['colorful']) is not bool:
        raise ValueError('colorful bir boolean olmalı.')
    return dict(value,color=color(value['color']))
