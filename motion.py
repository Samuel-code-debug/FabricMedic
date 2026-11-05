import ctypes
import math
import tkinter as tk
from ctypes import wintypes
from PIL import ImageGrab, ImageTk


def inverse(color):
    return '#%06x'%(0xffffff ^ int(color[1:],16))


def transition(app, host, change, radial=False):
    win=app.win
    if app.prefs.get('speed')=='关闭' or not host.winfo_viewable():
        change()
        return
    hwnd=int(win.frame(),0)
    rect=wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd,ctypes.byref(rect))
    try:
        snap=ImageGrab.grab(window=hwnd)
    except OSError:
        change()
        return
    x,y=host.winfo_rootx()-rect.left,host.winfo_rooty()-rect.top
    w,h=host.winfo_width(),host.winfo_height()
    old=snap.crop((x,y,x+w,y+h))
    change()
    layer=tk.Canvas(host,bd=0,highlightthickness=0)
    layer.place(x=0,y=0,width=w,height=h)
    layer.tk.call('raise',layer._w)
    photo=ImageTk.PhotoImage(old)
    layer.photo=photo
    layer.create_image(0,0,anchor='nw',image=photo)
    layer.update_idletasks()
    handle=wintypes.HWND(layer.winfo_id())
    g=ctypes.windll.gdi32
    g.CreateRectRgn.restype=g.CreateEllipticRgn.restype=wintypes.HANDLE
    cx=app.logo.winfo_rootx()-host.winfo_rootx()+9
    cy=app.logo.winfo_rooty()-host.winfo_rooty()+app.logo.winfo_height()//2
    def draw(t):
        mask=wintypes.HANDLE(g.CreateRectRgn(0,0,w,h))
        if radial:
            r=math.ceil(math.hypot(max(abs(cx),abs(w-cx)),max(abs(cy),abs(h-cy)))*t)
            hole=wintypes.HANDLE(g.CreateEllipticRgn(cx-r,cy-r,cx+r,cy+r))
            g.CombineRgn(mask,mask,hole,4)
            g.DeleteObject(hole)
        else:
            for i in range(4):
                p=max(0,min(1,t*1.24-i*.08))
                n=round(w*p)
                l,r=(0,n) if i%2==0 else (w-n,w)
                hole=wintypes.HANDLE(g.CreateRectRgn(l,h*i//4,r,h*(i+1)//4))
                g.CombineRgn(mask,mask,hole,4)
                g.DeleteObject(hole)
        if not ctypes.windll.user32.SetWindowRgn(handle,mask,1):
            g.DeleteObject(mask)
    app.ease(layer,draw,layer.destroy,motion='reveal')

def transition_page(app,page,change):
    """Move live Tk controls. Never sample a partially repainted window."""
    host=app.deck
    cancel=getattr(app,'finish_page',None)
    if cancel:
        cancel()
    if app.prefs.get('speed')=='关闭' or not host.winfo_viewable():
        change()
        return
    before,after=(app.home,app.settings) if page=='settings' else (app.settings,app.home)
    bg=app.colors[0]
    def tintable(rows):
        from tkinter import ttk
        collected=[]
        def visit(w,index):
            if isinstance(w,(tk.Label,ttk.Label)):
                classic=isinstance(w,tk.Label)
                orig=None if classic else w.cget('style')
                style=(orig or 'TLabel') if not classic else None
                color=w.cget('fg') if classic else app.style.lookup(style,'foreground')
                surface=w.cget('bg') if classic else app.style.lookup(style,'background') or bg
                ident='Motion'+str(w.winfo_id())+'.'+style if style else None
                if ident:w.configure(style=ident)
                rgb=lambda c:tuple(n//257 for n in host.winfo_rgb(c))
                collected.append((index,w,orig,color,ident,rgb(surface),rgb(color)))
            for child in w.winfo_children():visit(child,index)
        for i,w in enumerate(rows):visit(w,i)
        return collected
    def restore_colors(items):
        for _,w,orig,color,ident,*_ in items:
            if ident:w.configure(style=orig)
            else:w.configure(fg=color)
    def colorize(items,values):
        for i,w,_,_,ident,base,fg in items:
            alpha=values[i]
            color='#%02x%02x%02x'%tuple(round(a+(b-a)*alpha) for a,b in zip(base,fg))
            if ident:app.style.configure(ident,foreground=color)
            else:w.configure(fg=color)
    rows=before.pack_slaves()
    colors=tintable(rows)
    entered=False
    def enter():
        nonlocal rows,colors,entered
        before.place_forget()
        restore_colors(colors)
        change()
        after.place_configure(y=-16)
        rows=after.pack_slaves()
        colors=tintable(rows)
        entered=True
    def finish():
        app.finish_page=None
        job=app.anim.pop('page_live',None)
        if job:app.win.after_cancel(job)
        if not entered:enter()
        restore_colors(colors)
        after.place_configure(y=0)
    app.finish_page=finish
    exit_end=90
    total=exit_end+350+25*max(0,len(after.pack_slaves())-1)
    unit=lambda n:max(0,min(1,n))
    def frame(clock):
        ms=clock*total
        if not entered and ms>=exit_end:enter()
        if entered:
            age=ms-exit_end
            q=unit(age/350)
            dy=-5*(1-unit(age/250))**3-11*(1-q)**1.5*math.cos(1.5*math.pi*q)
            after.place_configure(y=round(dy))
            colorize(colors,[1-(1-unit((age-i*25)/100))**2 for i in range(len(rows))])
        else:
            before.place_configure(y=-round(6*unit(ms/exit_end)))
            colorize(colors,[1-unit((ms-i*10)/70) for i in range(len(rows))])
    app.ease('page_live',frame,finish,motion='page',seconds=total/1000)

def transition_refresh(app, host, change):
    """实例切换用：内容先上移，再按同一套弹簧曲线落回原位。

    和 transition_page 用的是同一个位移公式，只是不换页。
    """
    if app.prefs.get('speed')=='关闭' or not host.winfo_viewable():
        change()
        return
    change()
    total=420
    unit=lambda n:max(0.0,min(1.0,n))
    def frame(clock):
        age=clock*total
        q=unit(age/350)
        dy=-5*(1-unit(age/250))**3-11*(1-q)**1.5*math.cos(1.5*math.pi*q)
        host.place_configure(y=round(dy))
    app.ease('refresh',frame,motion='page',seconds=total/1000)

