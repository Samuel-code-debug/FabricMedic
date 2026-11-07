"""Window chrome and rounded Win32 child regions for the desktop workbench."""
import ctypes
from ctypes import wintypes
import os
import tkinter as tk
from tkinter import ttk
from motion import settle


def round_widget(widget, radius=9, circle=False):
    if os.name!='nt':
        return widget
    def shape(event):
        if event.widget!=widget:
            return
        w,h=event.width,event.height
        gdi=ctypes.windll.gdi32
        gdi.CreateRoundRectRgn.restype=wintypes.HANDLE
        gdi.CreateEllipticRgn.restype=wintypes.HANDLE
        region=(gdi.CreateEllipticRgn(4,4,w-3,h-3) if circle else
                gdi.CreateRoundRectRgn(0,0,w+1,h+1,radius*2,radius*2))
        if region and not ctypes.windll.user32.SetWindowRgn(wintypes.HWND(widget.winfo_id()),wintypes.HANDLE(region),1):
            gdi.DeleteObject(wintypes.HANDLE(region))
    widget.bind('<Configure>',shape,add='+')
    return widget


def round_window(window, radius=14):
    """Apply clipping after Tk has finished mapping or resizing its wrapper."""
    pending=[None]
    previous=[None]
    user=ctypes.windll.user32
    gdi=ctypes.windll.gdi32
    gdi.CreateRoundRectRgn.argtypes=[ctypes.c_int]*6
    gdi.CreateRoundRectRgn.restype=wintypes.HANDLE
    user.SetWindowRgn.argtypes=[wintypes.HWND,wintypes.HANDLE,wintypes.BOOL]
    user.SetWindowRgn.restype=ctypes.c_int
    gdi.DeleteObject.argtypes=[wintypes.HANDLE]
    def apply_shape():
        pending[0]=None
        if not window.winfo_exists() or not window.winfo_ismapped():
            return
        handle=wintypes.HWND(int(window.frame(),0))
        rect=wintypes.RECT()
        if not user.GetWindowRect(handle,ctypes.byref(rect)):
            return
        width,height=rect.right-rect.left,rect.bottom-rect.top
        geometry=(handle.value,width,height)
        if width<2 or height<2 or previous[0]==geometry:
            return
        region=gdi.CreateRoundRectRgn(0,0,width+1,height+1,radius*2,radius*2)
        if not region:return
        previous[0]=geometry
        if not user.SetWindowRgn(handle,region,True):
            previous[0]=None
            gdi.DeleteObject(region)
    def schedule(event):
        if event.widget is window and pending[0] is None:
            pending[0]=window.after(16,apply_shape)
    def cancel(event):
        if event.widget is window and pending[0] is not None:
            window.after_cancel(pending[0])
            pending[0]=None
    window.bind('<Configure>',schedule,add='+')
    window.bind('<Map>',schedule,add='+')
    window.bind('<Destroy>',cancel,add='+')


def titlebar(app):
    win=app.win
    win.overrideredirect(True)
    round_window(win)
    user=ctypes.windll.user32
    def handle():
        return wintypes.HWND(int(win.frame(),0))
    def close():
        if getattr(app,'closing',False):return
        if app.busy:return app.dialog('正在修复','请等待当前操作结束后再关闭。','error')
        app.closing=True
        alpha=float(win.attributes('-alpha'))
        def finish_close():
            for job in list(app.anim.values()):
                win.after_cancel(job)
            app.anim.clear()
            win.quit()
            win.destroy()
        app.ease('window',lambda t:win.attributes('-alpha',alpha*(1-t)),finish_close,seconds=.18,motion='window')
    win.protocol('WM_DELETE_WINDOW',close)
    def minimize():
        user.ShowWindow(handle(),6)
    bar=ttk.Frame(win,style='Cap.TFrame',padding=(14,5))
    bar.pack(fill='x')
    name=ttk.Label(bar,text='◈   Fabric Medic',style='Cap.TLabel')
    app.logo=name
    name.pack(side='left')
    arrow=tk.Canvas(bar,width=34,height=32,highlightthickness=0,bd=0,cursor='hand2')
    arrow.pack(side='left',padx=(0,12))
    arrow.create_line(9,13,17,20,25,13,width=3,tags='chevron')
    app.loader_arrow=arrow
    popup=None

    def dismiss(event=None):
        nonlocal popup
        if popup is not None:
            popup.destroy()
            popup=None

    def outside(event):
        if popup is not None and event.widget not in (name,arrow) and not str(event.widget).startswith(str(popup)+'.') and event.widget!=popup:
            dismiss()

    win.bind('<ButtonPress-1>',outside,add='+')
    win.bind('<Escape>',dismiss,add='+')
    def menu(event=None):
        nonlocal popup
        if popup is not None:
            dismiss()
            return
        if app.busy:return
        bg,side,sel,fg,muted,accent=app.colors
        panel=tk.Frame(win,bg=side,padx=8,pady=7)
        popup=panel
        def choose(mode):
            if app.busy:
                dismiss()
                app.dialog('正在查找','请先取消查找，再切换加载器。',mode='info')
                return
            if mode!=app.loader and (getattr(app,'proposed',set()) or getattr(app,'off',set())!=getattr(app,'initial_off',set())):
                dismiss()
                if not app.dialog('切换加载器','放弃当前未应用方案并重新扫描？'):return
            else:dismiss()
            app.loader=mode
            app.prefs['loader']=mode
            app.persist()
            name.configure(text='◈   '+mode.title()+' Medic')
            if app.folder:app.safe(app.scan)
            if app.page=="version":app.show_instance()
        for mode,details in [('fabric','Fabric 模组与依赖'),('forge','Forge 模组与依赖'),('mix','Forge 宿主 · Fabric 桥接')]:
            label=tk.Label(panel,text=mode.title()+('    ✓' if mode==app.loader else '')+'\n'+details,bg=sel if mode==app.loader else side,fg=fg,justify='left',anchor='w',width=21,padx=12,pady=6,cursor='hand2')
            label.pack(fill='x')
            label.bind('<ButtonRelease-1>',lambda e,m=mode:choose(m))
        x=name.winfo_rootx()-win.winfo_rootx()
        y=bar.winfo_y()+bar.winfo_height()+3
        panel.place(x=x,y=y-6)
        panel.lift()
        app.ease('loader_menu',lambda t:panel.place_configure(y=round(y-12*(1-settle(t)))) if popup is panel else None,motion='page',seconds=.35)
    name.configure(text='◈   '+app.loader.title()+' Medic',cursor='hand2')
    for target in (name,arrow):
        target.bind('<Button-1>',menu)
    def maximize():
        user.ShowWindow(handle(),9 if user.IsZoomed(handle()) else 3)
    movement={}
    def begin_move(event):
        if not user.IsZoomed(handle()) and not edge(event):
            cursor=wintypes.POINT()
            bounds=wintypes.RECT()
            if user.GetCursorPos(ctypes.byref(cursor)) and user.GetWindowRect(handle(),ctypes.byref(bounds)):
                movement.update(dx=cursor.x-bounds.left,dy=cursor.y-bounds.top)
    def move_window(event):
        if movement:
            cursor=wintypes.POINT()
            if user.GetCursorPos(ctypes.byref(cursor)):
                user.SetWindowPos(handle(),None,cursor.x-movement['dx'],cursor.y-movement['dy'],0,0,0x0015)
    bar.bind('<ButtonPress-1>',begin_move)
    bar.bind('<B1-Motion>',move_window)
    bar.bind('<ButtonRelease-1>',lambda e:movement.clear())
    app.button(bar,'说明',app.show_notice,caption=True).pack(side='left',padx=3)
    for title,cmd in [('×',close),('−',minimize)]:
        button=app.button(bar,title,cmd,caption=True)
        button.configure(font=('Segoe UI',19),width=2,padx=6,pady=0)
        button.pack(side='right',padx=1)
    def taskbar():
        hwnd=handle()
        ex=user.GetWindowLongW(hwnd,-20)
        user.SetWindowLongW(hwnd,-20,(ex | 0x40000) & ~0x80)
    win.bind('<Map>',lambda e:taskbar() if e.widget==win else None,add='+')
    # Borderless windows have no native resize frame. Hit-test the outer
    # client pixels on child widgets as well as on unused window space.
    gesture={}
    def edge(e):
        if user.IsZoomed(handle()):return ''
        x,y=e.x_root-win.winfo_rootx(),e.y_root-win.winfo_rooty()
        return ('w' if x<5 else 'e' if x>=win.winfo_width()-5 else '')+('n' if y<5 else 's' if y>=win.winfo_height()-5 else '')
    def start(e):
        side='es' if e.widget is grip else edge(e)
        if side:
            gesture.update(side=side,x=e.x_root,y=e.y_root,l=win.winfo_rootx(),t=win.winfo_rooty(),w=win.winfo_width(),h=win.winfo_height())
    def resize(e):
        if not gesture:return
        g=gesture
        dx,dy=e.x_root-g['x'],e.y_root-g['y']
        side=g['side']
        mw,mh=win.minsize()
        w=max(mw,g['w']+(-dx if 'w' in side else dx if 'e' in side else 0))
        h=max(mh,g['h']+(-dy if 'n' in side else dy if 's' in side else 0))
        l=g['l']+(g['w']-w if 'w' in side else 0)
        t=g['t']+(g['h']-h if 'n' in side else 0)
        win.geometry(f'{w}x{h}+{l}+{t}')
    grip=tk.Label(win,text='◢',bd=0,font=('Segoe UI',9),cursor='size_nw_se')
    app.resize_grip=grip
    win.after_idle(lambda: (grip.place(relx=1,rely=1,anchor='se'),grip.lift()))
    win.bind('<ButtonPress-1>',start,add='+')
    win.bind('<B1-Motion>',resize,add='+')
    win.bind('<ButtonRelease-1>',lambda e:gesture.clear(),add='+')


class Scrollbar(tk.Canvas):
    def __init__(self,parent,orient,command):
        self.horizontal=orient=='horizontal'
        super().__init__(parent,width=12,height=12,bd=0,highlightthickness=0)
        self.command=command
        self.first,self.last=0.,1.
        self.offset=0
        self.color='#999999'
        self.bind('<Configure>',lambda e:self.draw())
        self.bind('<Button-1>',self.press)
        self.bind('<B1-Motion>',self.drag)

    def set(self,first,last):
        self.first,self.last=float(first),float(last)
        self.draw()

    def draw(self):
        self.delete('all')
        length=self.winfo_width() if self.horizontal else self.winfo_height()
        span=self.last-self.first
        self.size=min(length,max(24,round(length*span)))
        self.travel=length-self.size
        self.start=self.travel*self.first/(1-span) if span<1 else 0
        if span>=.99999 or self.size<8:
            return
        x,y=(self.start+4,6) if self.horizontal else (6,self.start+4)
        dx,dy=(self.size-8,0) if self.horizontal else (0,self.size-8)
        self.create_line(x,y,x+dx,y+dy,width=7,capstyle='round',fill=self.color)

    def press(self,e):
        pos=e.x if self.horizontal else e.y
        self.offset=pos-self.start if self.start<=pos<=self.start+self.size else self.size/2
        self.drag(e)

    def drag(self,e):
        if self.travel>0:
            pos=e.x if self.horizontal else e.y
            self.command('moveto',max(0,min(1,(pos-self.offset)/self.travel))*(1-self.last+self.first))

