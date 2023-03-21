import curses

from visidata import vd, VisiData, BaseSheet, Sheet, AttrDict


# registry of mouse events.  cleared before every draw cycle.
vd.mousereg = []  # list of AttrDict(winname=, winscr=, y=, x=, h=, w=, buttonfuncs=dict)

# sheet mouse position for current mouse event
BaseSheet.init('mouseX', int)
BaseSheet.init('mouseY', int)


@VisiData.after
def initCurses(vd):
    curses.MOUSE_ALL = 0xffffffff
    curses.mousemask(curses.MOUSE_ALL if vd.options.mouse_interval else 0)
    curses.mouseinterval(vd.options.mouse_interval)
    curses.mouseEvents = {}

    for k in dir(curses):
        if k.startswith('BUTTON') or k in ('REPORT_MOUSE_POSITION', '2097152'):
            curses.mouseEvents[getattr(curses, k)] = k


@VisiData.after
def clearCaches(vd):
    vd.mousereg = []


@VisiData.api
def onMouse(self, scr, y, x, h, w, winname='', **kwargs):
    py, px = scr.getparyx()
    if py > 0:
        y += py
        x += px

    e = AttrDict(winname=winname, winscr=scr, y=y, x=x, h=h, w=w, buttonfuncs=kwargs)
    self.mousereg.append(e)


@VisiData.api
def getMouse(self, _scr, _x, _y, button):
    for reg in self.mousereg[::-1]:
        if reg.x <= _x < reg.x+reg.w and reg.y <= _y < reg.y+reg.h and button in reg.buttonfuncs:
            return reg.buttonfuncs[button]


@VisiData.api
def parseMouse(vd, **kwargs):
    'Return list of mouse interactions (clicktype, y, x, name, scr) for curses screens given in kwargs as name:scr.'

    devid, x, y, z, bstate = curses.getmouse()

    clicktype = ''
    if bstate & curses.BUTTON_CTRL:
        clicktype += "CTRL-"
        bstate &= ~curses.BUTTON_CTRL
    if bstate & curses.BUTTON_ALT:
        clicktype += "ALT-"
        bstate &= ~curses.BUTTON_ALT
    if bstate & curses.BUTTON_SHIFT:
        clicktype += "SHIFT-"
        bstate &= ~curses.BUTTON_SHIFT

    keystroke = clicktype + curses.mouseEvents.get(bstate, str(bstate))
    ret = AttrDict(keystroke=keystroke, y=y, x=x, found=[])
    for winname, winscr in kwargs.items():
        py, px = winscr.getparyx()
        mh, mw = winscr.getmaxyx()
        if py <= y < py+mh and px <= x < px+mw:
            ret.found.append(winname)
#            vd.debug(f'{keystroke} at ({x-px}, {y-py}) in window {winname} {winscr}')

    return ret


@VisiData.api
def handleMouse(vd, sheet):
    try:
        vd.keystrokes = ''
        pct = vd.windowConfig['pct']
        topPaneActive = ((vd.activePane == 2 and pct < 0)  or (vd.activePane == 1 and pct > 0))
        bottomPaneActive = ((vd.activePane == 1 and pct < 0)  or (vd.activePane == 2 and pct > 0))

        r = vd.parseMouse(top=vd.winTop, bot=vd.winBottom, menu=vd.scrMenu)
        if (bottomPaneActive and 'top' in r.found) or (topPaneActive and 'bot' in r.found):
            vd.activePane = 1 if vd.activePane == 2 else 2
            sheet = vd.activeSheet

        f = vd.getMouse(r.winscr, r.x, r.y, r.keystroke)
        sheet.mouseX, sheet.mouseY = r.x, r.y-1
        if f:
            if isinstance(f, str):
                for cmd in f.split():
                    sheet.execCommand(cmd)
            else:
                f(r.y, r.x, r.keystroke)

            vd.keystrokes = vd.prettykeys(r.keystroke)
            return ''  #  handled

    except curses.error:
        pass

    return r.keystroke


@Sheet.api
def visibleColAtX(self, x):
    for vcolidx, (colx, w) in self._visibleColLayout.items():
        if colx <= x <= colx+w:
            return vcolidx


@Sheet.api
def visibleRowAtY(self, y):
    for rowidx, (rowy, h) in self._rowLayout.items():
        if rowy <= y <= rowy+h-1:
            return rowidx

@Sheet.command('BUTTON1_PRESSED', 'go-mouse', 'set cursor to row and column where mouse was clicked')
def go_mouse(sheet):
    ridx = sheet.visibleRowAtY(sheet.mouseY)
    if ridx is not None:
        sheet.cursorRowIndex = ridx
    cidx = sheet.visibleColAtX(sheet.mouseX)
    if cidx is not None:
        sheet.cursorVisibleColIndex = cidx

Sheet.addCommand(None, 'scroll-mouse', 'sheet.topRowIndex=cursorRowIndex-mouseY+1', 'scroll to mouse cursor location'),

Sheet.addCommand('ScrollwheelUp', 'scroll-up', 'cursorDown(options.scroll_incr); sheet.topRowIndex += options.scroll_incr', 'scroll one row up'),
Sheet.addCommand('ScrollwheelDown', 'scroll-down', 'cursorDown(-options.scroll_incr); sheet.topRowIndex -= options.scroll_incr', 'scroll one row down'),