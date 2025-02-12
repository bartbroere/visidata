import unicodedata
import sys
import re
import functools
import textwrap

from visidata import options, drawcache, vd, update_attr, colors, ColorAttr

disp_column_fill = ' '
internal_markup_re = r'(\[:[^\]]*?\])'  # [:whatever until the closing bracket] or [:]

### Curses helpers

# ZERO_WIDTH_CF is from wcwidth:
# NOTE: created by hand, there isn't anything identifiable other than
# general Cf category code to identify these, and some characters in Cf
# category code are of non-zero width.
# Also includes some Cc, Mn, Zl, and Zp characters
ZERO_WIDTH_CF = set(map(chr, [
    0,       # Null (Cc)
    0x034F,  # Combining grapheme joiner (Mn)
    0x200B,  # Zero width space
    0x200C,  # Zero width non-joiner
    0x200D,  # Zero width joiner
    0x200E,  # Left-to-right mark
    0x200F,  # Right-to-left mark
    0x2028,  # Line separator (Zl)
    0x2029,  # Paragraph separator (Zp)
    0x202A,  # Left-to-right embedding
    0x202B,  # Right-to-left embedding
    0x202C,  # Pop directional formatting
    0x202D,  # Left-to-right override
    0x202E,  # Right-to-left override
    0x2060,  # Word joiner
    0x2061,  # Function application
    0x2062,  # Invisible times
    0x2063,  # Invisible separator
]))

def wcwidth(cc, ambig=1):
        if cc in ZERO_WIDTH_CF:
            return 1
        eaw = unicodedata.east_asian_width(cc)
        if eaw in 'AN':  # ambiguous or neutral
            if unicodedata.category(cc) == 'Mn':
                return 1
            else:
                return ambig
        elif eaw in 'WF': # wide/full
            return 2
        elif not unicodedata.combining(cc):
            return 1
        return 0


def iterchunks(s, literal=False):
    chunks = re.split(internal_markup_re, s)
    for chunk in chunks:
        if not chunk:
            continue
        if not literal and chunk.startswith('[:') and chunk.endswith(']'):
            yield chunk[2:-1] or ':', ''  # color/attr change
        else:
            yield '', chunk


@functools.lru_cache(maxsize=100000)
def dispwidth(ss, maxwidth=None, literal=False):
    'Return display width of string, according to unicodedata width and options.disp_ambig_width.'
    disp_ambig_width = options.disp_ambig_width
    w = 0

    for _, s in iterchunks(ss, literal=literal):
        for cc in s:
            if cc:
                w += wcwidth(cc, disp_ambig_width)
                if maxwidth and w > maxwidth:
                    break
    return w


@functools.lru_cache(maxsize=100000)
def _dispch(c, oddspacech=None, combch=None, modch=None):
    ccat = unicodedata.category(c)
    if ccat in ['Mn', 'Sk', 'Lm']:
        if unicodedata.name(c).startswith('MODIFIER'):
            return modch, 1
    elif c != ' ' and ccat in ('Cc', 'Zs', 'Zl', 'Cs'):  # control char, space, line sep, surrogate
        return oddspacech, 1
    elif c in ZERO_WIDTH_CF:
        return combch, 1

    return c, dispwidth(c, literal=True)


def iterchars(x):
    if isinstance(x, dict):
        yield from '{%d}' % len(x)
        for k, v in x.items():
            yield ' '
            yield from iterchars(k)
            yield '='
            yield from iterchars(v)

    elif isinstance(x, (list, tuple)):
        yield from '[%d] ' % len(x)
        for i, v in enumerate(x):
            if i != 0:
                yield from '; '
            yield from iterchars(v)

    else:
        yield from str(x)


@functools.lru_cache(maxsize=100000)
def _clipstr(s, dispw, trunch='', oddspacech='', combch='', modch=''):
    '''Return clipped string and width in terminal display characters.
    Note: width may differ from len(s) if East Asian chars are 'fullwidth'.'''
    w = 0
    ret = ''

    trunchlen = dispwidth(trunch)
    for c in s:
        newc, chlen = _dispch(c, oddspacech=oddspacech, combch=combch, modch=modch)
        if newc:
            ret += newc
            w += chlen
        else:
            ret += c
            w += dispwidth(c)

        if dispw and w > dispw-trunchlen+1:
            ret = ret[:-2] + trunch # replace final char with ellipsis
            w += trunchlen
            break

    return ret, w


@drawcache
def clipstr(s, dispw, truncator=None, oddspace=None):
    if options.visibility:
        return _clipstr(s, dispw,
                        trunch=options.disp_truncator if truncator is None else truncator,
                        oddspacech=options.disp_oddspace if oddspace is None else oddspace,
                        modch='\u25e6',
                        combch='\u25cc')
    else:
        return _clipstr(s, dispw,
                trunch=options.disp_truncator if truncator is None else truncator,
                oddspacech=options.disp_oddspace if oddspace is None else oddspace,
                modch='',
                combch='')

def clipdraw(scr, y, x, s, attr, w=None, clear=True, rtl=False, literal=False, **kwargs):
    '''Draw string `s` at (y,x)-(y,x+w) with curses attr, clipping with ellipsis char.  
      If `rtl`, draw inside (x-w, x).
      If `clear`, clear whole editing area before displaying.
      If `literal`, do not interpret [:color]codes[:].
     Return width drawn (max of w).
    '''
    if scr:
        _, windowWidth = scr.getmaxyx()
    else:
        windowWidth = 80
    totaldispw = 0

    if not isinstance(attr, ColorAttr):
        cattr = ColorAttr(attr, 0, 0, attr)
    else:
        cattr = attr

    origattr = cattr
    origw = w
    clipped = ''
    link = ''

    try:
        for colorname, chunk in iterchunks(s, literal=literal):
            if colorname.startswith('onclick'):
                link = colorname
                colorname = 'clickable'

            if colorname == ':':
                link = ''
                cattr = origattr
                continue

            if colorname:
                cattr = update_attr(cattr, colors.get_color(colorname), 8)

            if not chunk:
                continue

            if origw is None:
                chunkw = dispwidth(chunk, maxwidth=windowWidth-totaldispw)
            else:
                chunkw = origw

            chunkw = min(chunkw, (x-1) if rtl else (windowWidth-x-1))
            if chunkw <= 0:  # no room anyway
                return totaldispw
            if not scr:
                return totaldispw

            # convert to string just before drawing
            clipped, dispw = clipstr(chunk, chunkw, **kwargs)
            if rtl:
                # clearing whole area (w) has negative display effects; clearing just dispw area is useless
                # scr.addstr(y, x-dispw-1, disp_column_fill*dispw, attr)
                scr.addstr(y, x-dispw-1, clipped, cattr.attr)
            else:
                if clear:
                    scr.addstr(y, x, disp_column_fill*chunkw, cattr.attr)  # clear whole area before displaying
                scr.addstr(y, x, clipped, cattr.attr)

            if link:
                vd.onMouse(scr, x, y, dispw, 1, BUTTON1_RELEASED=link)

            x += dispw
            totaldispw += dispw

            if chunkw < dispw:
                break
    except Exception as e:
        if vd.options.debug:
            raise
#        raise type(e)('%s [clip_draw y=%s x=%s dispw=%s w=%s clippedlen=%s]' % (e, y, x, totaldispw, w, len(clipped))
#                ).with_traceback(sys.exc_info()[2])

    return totaldispw


def _markdown_to_internal(text):
    'Return markdown-formatted `text` converted to internal formatting (like `[:color]text[:]`).'
    text = re.sub(r'`(.*?)`', r'[:code]\1[:]', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'[:bold]\1[:]', text)
    text = re.sub(r'\*(.*?)\*', r'[:italic]\1[:]', text)
    text = re.sub(r'\b_(.*?)_\b', r'[:underline]\1[:]', text)
    return text


def wraptext(text, width=80, indent=''):
    '''
    Word-wrap `text` and yield (formatted_line, textonly_line) for each line of at most `width` characters.
    Formatting like `[:color]text[:]` is ignored for purposes of computing width, and not included in `textonly_line`.
    '''
    import re

    for line in text.splitlines():
        if not line:
            yield '', ''
            continue

        line = _markdown_to_internal(line)
        chunks = re.split(internal_markup_re, line)
        textchunks = [x for x in chunks if not (x.startswith('[:') and x.endswith(']'))]
        for linenum, textline in enumerate(textwrap.wrap(''.join(textchunks), width=width, drop_whitespace=False)):
            txt = textline
            r = ''
            while chunks:
                c = chunks[0]
                if len(c) > len(txt):
                    r += txt
                    chunks[0] = c[len(txt):]
                    break

                if len(chunks) == 1:
                    r += chunks.pop(0)
                else:
                    chunks.pop(0)
                    r += txt[:len(c)] + chunks.pop(0)

                txt = txt[len(c):]

            if linenum > 0:
                r = indent + r
            yield r, textline

        for c in chunks:
            yield c, ''


def clipbox(scr, lines, attr, title=''):
    scr.erase()
    scr.bkgd(attr)
    scr.box()
    h, w = scr.getmaxyx()
    for i, line in enumerate(lines):
        clipdraw(scr, i+1, 2, line, attr)

    clipdraw(scr, 0, w-len(title)-6, f"| {title} |", attr)


vd.addGlobals(clipstr=clipstr,
              clipdraw=clipdraw,
              clipbox=clipbox,
              dispwidth=dispwidth,
              iterchars=iterchars,
              wraptext=wraptext)
