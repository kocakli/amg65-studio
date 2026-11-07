"""Render real remaining allowances on the AMG65's 63 × 5 LED matrix.

The output is logical left-to-right RGB pixels. USB memory ordering belongs to
the transport. A=Claude, X=Codex, C=Cursor; numbers are percentages remaining.
"""
from __future__ import annotations

import math

WIDTH, HEIGHT = 63, 5
# LED-specific colours, rather than uncalibrated monitor RGB. Less green makes
# Claude more saturated on an emissive strip. Lower blue removes the pale cast;
# user brightness still scales every channel. This is not a measured colour match.
COLORS = {"claude": (254, 78, 6), "codex": (123, 220, 176), "cursor": (134, 190, 248)}
PROVIDERS = (("claude", "A"), ("codex", "X"), ("cursor", "C"))
UNKNOWN = (132, 144, 157)
BLACK = (0, 0, 0)
ATTENTION = (254, 180, 54)
ERROR = (250, 76, 90)
FONT = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "A": ("010", "101", "111", "101", "101"),
    "C": ("011", "100", "100", "100", "011"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "L": ("100", "100", "100", "100", "111"),
    "O": ("111", "101", "101", "101", "111"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "U": ("101", "101", "101", "101", "111"),
    "X": ("101", "101", "010", "101", "101"),
    "-": ("000", "000", "111", "000", "000"),
    "%": ("101", "001", "010", "100", "101"),
    "?": ("111", "001", "011", "000", "010"),
    " ": ("0", "0", "0", "0", "0"),
}

FONT.update({
    'B':('110','101','110','101','110'),'F':('111','100','110','100','100'),
    'G':('011','100','101','101','011'),'H':('101','101','111','101','101'),
    'I':('111','010','010','010','111'),'J':('001','001','001','101','010'),
    'K':('101','110','100','110','101'),'M':('10001','11011','10101','10001','10001'),
    'N':('1001','1101','1011','1001','1001'),'P':('110','101','110','100','100'),
    'Q':('111','101','101','111','001'),'T':('111','010','010','010','010'),
    'V':('101','101','101','101','010'),'W':('10001','10001','10101','11011','01010'),
    'Y':('101','101','010','010','010'),'Z':('111','001','010','100','111'),
    '.':('0','0','0','0','1'),':':('0','1','0','1','0'),
    '!':('1','1','1','0','1'),'/':('001','001','010','100','100'),
})


def _value(provider):
    value = provider.get("remaining_percent")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and 0 <= value <= 100 else None


def _color(provider, brightness):
    factor = brightness * (0.45 if provider.get("stale") else 1.0)
    rgb = COLORS.get(provider.get("id"), UNKNOWN) if _value(provider) is not None else UNKNOWN
    return tuple(round(min(254, channel) * factor) for channel in rgb)


def _brightness(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("brightness must be a finite number between 0 and 1")
    if not 0 <= value <= 1:
        raise ValueError("brightness must be between 0 and 1")
    return value


def _text(pixels, text, x, color, right=56):
    for char in text:
        glyph = FONT.get(char, FONT["?"])
        for y, row in enumerate(glyph):
            for dx, bit in enumerate(row):
                if bit == "1" and 0 <= x + dx < right:
                    pixels[y * WIDTH + x + dx] = color
        x += len(glyph[0]) + 1


def text_width(text):
    """Exact five-row bitmap width, including only inter-character spacing."""
    return max(0, sum(len(FONT.get(char, FONT['?'])[0]) + 1 for char in text) - 1)


def _icon(pixels, rows, x, color):
    for y, row in enumerate(rows):
        for dx, bit in enumerate(row):
            if bit == '1' and 0 <= x + dx < WIDTH:
                pixels[y * WIDTH + x + dx] = color


STATE_ICONS = {
    'queued': ('01110', '10001', '10101', '10001', '01110'),
    'waiting_approval': ('00100', '00100', '00100', '00000', '00100'),
    'waiting_input': ('01110', '00010', '00100', '00000', '00100'),
    'completed': ('00001', '00010', '10100', '01000', '00000'),
    'error': ('10001', '01010', '00100', '01010', '10001'),
}


def _bars(pixels, providers, brightness):
    for index, provider in enumerate(providers):
        x = 57 + index * 2
        value = _value(provider)
        color = _color(provider, brightness)
        if value is None:
            pixels[2 * WIDTH + x] = color
            continue
        # A nonzero allowance always retains one visible level. Zero is only
        # represented by a dim baseline, distinct from unavailable (middle dot).
        height = math.ceil(value / 20)
        for y in range(5):
            pixels[y * WIDTH + x] = color if y >= 5 - height else tuple(v // 10 for v in color)


def render_overview(snapshot: dict, brightness: float = 0.4) -> list[tuple[int, int, int]]:
    """Three aligned quota cells in 56 columns, with three right-side meters.

    Unknown values are ``--``. Stale values are dimmed and marked with a small
    amber pixel at the end of their cell. No percentages are inferred from errors.
    """
    brightness = _brightness(brightness)
    pixels = [BLACK] * (WIDTH * HEIGHT)
    entries = {p.get("id"): p for p in snapshot.get("providers", []) if isinstance(p, dict)}
    providers = []
    for index, (provider_id, letter) in enumerate(PROVIDERS):
        provider = entries.get(provider_id, {"id": provider_id})
        providers.append(provider)
        value = _value(provider)
        text = str(round(value)) if value is not None else "--"
        left = index * 19
        color = _color(provider, brightness)
        _text(pixels, letter, left, color, left + 3)
        _text(pixels, text, left + 16 - text_width(text), color, left + 16)
        if provider.get("stale"):
            pixels[min(55, left + 17)] = tuple(round(v * brightness) for v in ATTENTION)
    _bars(pixels, providers, brightness)
    return pixels


def render_detail(provider: dict, brightness: float = 0.4) -> list[tuple[int, int, int]]:
    """Show a provider's full name and its selected remaining percentage."""
    brightness = _brightness(brightness)
    pixels = [BLACK] * (WIDTH * HEIGHT)
    label = {"claude": "CLAUDE", "codex": "CODEX", "cursor": "CURSOR"}.get(provider.get("id"), "?")
    color = _color(provider, brightness)
    _text(pixels, label, 1, color)
    value = _value(provider)
    text = "--" if value is None else f"{round(value)}%"
    _text(pixels, text, 51 - text_width(text), color, 51)
    if provider.get("stale"):
        _text(pixels, "?", 58, tuple(round(v * brightness) for v in ATTENTION), 63)
    elif value is None:
        _text(pixels, "?", 58, color, 63)
    else:
        height = math.ceil(value / 20)
        for x in (58, 59, 60):
            for y in range(5):
                pixels[y * WIDTH + x] = color if y >= 5 - height else tuple(v // 10 for v in color)
    return pixels


def render_text(text: str, hex_color: str, brightness: float, elapsed: float=0, *, marquee=False) -> list[tuple[int,int,int]]:
    """Bounded marquee; short text stays centered, long text scrolls at 2px/s."""
    brightness=_brightness(brightness)
    rgb=tuple(round(min(254,int(hex_color[i:i+2],16))*brightness) for i in (1,3,5))
    width=text_width(text)
    pixels=[BLACK]*(WIDTH*HEIGHT)
    if marquee:
        # Start visible, repeat the whole message with a ten-pixel gap. Even a
        # short message moves; long messages are not cropped before scrolling.
        period=max(1,width+10)
        x=-int(max(0,elapsed)*2)%period-period
        while x<56:
            _text(pixels,text,x,rgb)
            x+=period
    else:
        x=max(0,(56-width)//2) if width<=56 else 56-int(max(0,elapsed)*2)%(width+68)
        _text(pixels,text,x,rgb)
    _icon(pixels,('11111','00100','00100','00100','00100'),58,rgb)
    return pixels


def _scale(rgb, factor):
    # Limit the factor once, preserving hue instead of clipping each channel.
    peak=max(rgb)
    factor=min(factor,254/peak) if peak else factor
    return tuple(round(channel*factor) for channel in rgb)


def apply_text_effect(frame, effect, brightness=0.4, elapsed=0, *, left=0):
    """Decorate an already brightness-scaled text frame, never attention alerts.

    The independent seven-column gauge stays intact. Matrix moves complete
    glyph-column groups downward, then holds the readable text between waves.
    All temporal steps are quantized to the worker's existing two-frame cadence.
    Other effects keep text in place. Matrix rain occupies only empty pixels.
    """
    brightness=_brightness(brightness)
    if effect not in ('none','scan','breathe','matrix','scroll'):
        raise ValueError('unknown text effect')
    if len(frame)!=WIDTH*HEIGHT:
        raise ValueError('a 63 by 5 frame is required')
    if type(left) is not int or not 0<=left<56:
        raise ValueError('invalid text boundary')
    pixels=list(frame)
    if effect=='none' or brightness==0:
        return pixels
    step=int(max(0,elapsed)*2)
    if effect=='scroll':
        span=56-left
        offset=step%(span+8)
        for y in range(HEIGHT):
            for x in range(span):
                source=(x+offset)%(span+8)
                pixels[y*WIDTH+left+x]=frame[y*WIDTH+left+source] if source<span else BLACK
    elif effect=='breathe':
        factor=0.92+0.08*math.cos(step*math.tau/12)
        for y in range(HEIGHT):
            for x in range(left,56):
                index=y*WIDTH+x
                pixels[index]=_scale(frame[index],factor)
    elif effect=='scan':
        head=(step*3)%64-4
        for y in range(HEIGHT):
            for x in range(left,56):
                distance=abs(x-head)
                factor=1.25 if distance<2 else 1.05 if distance<4 else 0.85
                index=y*WIDTH+x
                pixels[index]=_scale(frame[index],factor)
    else:
        # Split on genuinely empty columns so each bitmap character falls as one
        # piece, including our variable-width glyphs. A five-row display cannot
        # show tall rain: wrap whole glyphs downward, then let them settle.
        columns=[x for x in range(left,56) if any(frame[y*WIDTH+x]!=BLACK for y in range(HEIGHT))]
        groups=[]
        for x in columns:
            if not groups or x>groups[-1][-1]+1:groups.append([])
            groups[-1].append(x)
        for y in range(HEIGHT):
            pixels[y*WIDTH+left:y*WIDTH+56]=[BLACK]*(56-left)
        phase=step%11
        for index,group in enumerate(groups):
            fall=phase-index%3
            offset=fall if 0<fall<HEIGHT else 0
            for x in group:
                for y in range(HEIGHT):
                    pixels[((y+offset)%HEIGHT)*WIDTH+x]=frame[y*WIDTH+x]
        for x in range(left+2,56,5):
            head=(step+(x//5)*3)%11-3
            for tail in range(3):
                y=head-tail
                if 0<=y<HEIGHT:
                    index=y*WIDTH+x
                    if pixels[index]==BLACK:
                        pixels[index]=_scale((20,168,72),brightness*0.24/(tail+1))
    return pixels

ACTIVITY_LABELS = {'running':'RUN','queued':'QUEUE','waiting_approval':'ASK',
                   'waiting_input':'INPUT','completed':'DONE','error':'ERROR'}
ACTIVITY_PRIORITY = {'waiting_approval':5,'waiting_input':5,'error':4,'running':3,'queued':2,'completed':1}
WORK_LABELS = {'working':'RUN','using_tool':'TOOL','running_command':'EXEC',
               'reading_files':'READ','editing_files':'EDIT','searching':'FIND',
               'compacting':'CTX','input_received':'READY'}


def activity_label(activity):
    """Fixed host metadata only; unknown tool names/arguments are never text."""
    state=activity.get('state')
    summary=activity.get('summary')
    return (WORK_LABELS.get(summary,'RUN') if isinstance(summary,str) else 'RUN') if state=='running' else ACTIVITY_LABELS.get(state,'')


def select_activity(activity, elapsed=0, now=None, *, provider='all'):
    """Prefer genuine attention events; rotate equally urgent providers fairly."""
    import time
    now=time.time() if now is None else now
    if provider not in ('all','claude','codex','cursor'):return None
    if not isinstance(activity,dict): return None
    rows=activity.get('providers',[])
    candidates=[]
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict) or row.get('provider') not in COLORS or row.get('state') not in ACTIVITY_LABELS:
            continue
        if provider!='all' and row['provider']!=provider:continue
        expires=row.get('expires_at')
        if isinstance(expires,bool) or not isinstance(expires,(int,float)) or not math.isfinite(expires) or expires <= now:
            continue
        if row.get('stale'): continue
        candidates.append(row)
    if not candidates: return None
    priority=max(ACTIVITY_PRIORITY[row['state']] for row in candidates)
    rows=[row for row in candidates if ACTIVITY_PRIORITY[row['state']]==priority]
    # Working states leave four seconds in each ten-second cycle for allowances.
    if provider=='all' and priority in (2,3) and int(max(0,elapsed))%10 >= 6: return None
    return rows[int(max(0,elapsed)//4)%len(rows)]


def render_activity(activity, snapshot, brightness=0.4, elapsed=0):
    """A distinct state icon, full provider name, state code and three quota rails.

    No prompt, command or filename is placed on the physical display. ASCII state
    codes remain legible in the device's five rows, regardless of UI language.
    """
    brightness=_brightness(brightness)
    pixels=[BLACK]*(WIDTH*HEIGHT)
    provider=activity.get('provider')
    state=activity.get('state')
    if provider not in COLORS or state not in ACTIVITY_LABELS: return pixels
    color=tuple(round(min(254,v)*brightness) for v in COLORS[provider])
    label={'codex':'CODEX','claude':'CLAUDE','cursor':'CURSOR'}[provider]
    _text(pixels,label,7,color,30)
    _text(pixels,activity_label(activity),32,color,53)
    # Only this tiny icon moves, at two steps per second. Names and attention
    # states stay steady; the transport's existing frame/ACK cadence is unchanged.
    if state == 'running':
        orbit=((2,0),(4,2),(2,4),(0,2))
        active=int(max(0,elapsed)*2)%len(orbit)
        for index,(x,y) in enumerate(orbit):
            pixels[y*WIDTH+x]=color if index==active else tuple(v//5 for v in color)
        pixels[2*WIDTH+2]=color
    else:
        accent=ATTENTION if state in ('waiting_approval','waiting_input') else ERROR if state=='error' else COLORS[provider]
        _icon(pixels,STATE_ICONS[state],0,tuple(round(v*brightness) for v in accent))
    entries={row.get('id'):row for row in snapshot.get('providers',[]) if isinstance(row,dict)}
    _bars(pixels,[entries.get(p,{'id':p}) for p,_ in PROVIDERS],brightness)
    return pixels


# Original five-row interpretation of the blocky Claude Code character, not an
# imported sprite or a reduced high-resolution image. Four legs and two dark
# eyes survive at this height; richer scenes belong on the TFT, not this strip.
CLAUDE_SPRITE = ('00111111100','11101110111','00111111100','00111111100','00101010100')
CLAUDE_WALK_LEGS = ('01010010100','00101001010')
# Original Studio characters, not official Codex/Cursor brand mascots. Codex's
# antenna and two feet contrast with Cursor's pointed, single-eyed arrow body.
CODEX_SPRITE = ('00000100000','00111111100','01101110110','00111111100','00011011000')
CURSOR_SPRITE = ('00000001000','00111111100','11110111111','00111111100','00000001000')
MASCOT_SPRITES = {'claude':CLAUDE_SPRITE,'codex':CODEX_SPRITE,'cursor':CURSOR_SPRITE}
MASCOT_LETTERS = dict(PROVIDERS)


def render_mascot(activity, snapshot, brightness=0.4, elapsed=0):
    """An observed tool state as its actor, a state word and three quota rails.

    RUN takes twelve visual steps to walk out and back. Waiting/error poses are
    stationary; no guessed state, task text or permission decision enters here.
    """
    brightness=_brightness(brightness)
    provider=activity.get('provider')
    if provider not in MASCOT_SPRITES or activity.get('state') not in ACTIVITY_LABELS:
        return render_activity(activity,snapshot,brightness,elapsed)
    pixels=[BLACK]*(WIDTH*HEIGHT)
    state=activity['state']
    step=int(max(0,elapsed)*2)
    rows=list(MASCOT_SPRITES[provider])
    x=3
    facing=0
    color=tuple(round(channel*brightness) for channel in COLORS[provider])
    if state=='running':
        travel=step%12
        x=1+2*(travel if travel<=6 else 12-travel)
        facing=1 if 0<travel<=6 else -1
        if provider=='claude':
            rows[4]=CLAUDE_WALK_LEGS[step%2]
        elif provider=='codex':
            rows[4]=('00011011000','00110001100')[step%2]
            rows[0]=('00000100000','00000010000')[step%2]
        elif step%2:
            rows[2]='11111011111'
    elif state=='completed':
        x=5
        if step%2:
            rows[0]={'claude':'10111111101','codex':'01000100010','cursor':'10000001001'}[provider]
    elif state=='error':
        color=_scale(color,0.55)
    if facing and provider=='claude':
        eyes=['1']*11
        for eye in (3+facing,7+facing):eyes[eye]='0'
        rows[1]=''.join(eyes)
    elif facing==-1 and provider=='cursor':
        rows=[row[::-1] for row in rows]
    _icon(pixels,rows,x,color)
    if state!='running':
        accent=ATTENTION if state in ('waiting_approval','waiting_input') else ERROR if state=='error' else COLORS[provider]
        _icon(pixels,STATE_ICONS[state],18,tuple(round(v*brightness) for v in accent))
    # The A/X/C mapping remains identical to the overview legend. The longest state,
    # INPUT, ends at column 51; the sprite never reaches the label at column 26.
    _text(pixels,MASCOT_LETTERS[provider],26,tuple(round(v*brightness) for v in COLORS[provider]),29)
    state_color=tuple(round(v*brightness) for v in ERROR) if state=='error' else tuple(round(v*brightness) for v in COLORS[provider])
    _text(pixels,activity_label(activity),32,state_color,53)
    entries={row.get('id'):row for row in snapshot.get('providers',[]) if isinstance(row,dict)}
    _bars(pixels,[entries.get(p,{'id':p}) for p,_ in PROVIDERS],brightness)
    return pixels


def render_claude_mascot(activity, snapshot, brightness=0.4, elapsed=0):
    """Compatibility entry point for older Claude-only preview integrations."""
    if activity.get('provider')!='claude':
        return render_activity(activity,snapshot,brightness,elapsed)
    return render_mascot(activity,snapshot,brightness,elapsed)
