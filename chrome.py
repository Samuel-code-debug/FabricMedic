"""Window chrome and rounded Win32 child regions for the desktop workbench."""
import ctypes
import math
from ctypes import wintypes
import os
import tkinter as tk
from tkinter import ttk


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


def titlebar(app):
    win=app.win
    win.overrideredirect(True)
    user=ctypes.windll.user32
    def handle():
        return wintypes.HWND(int(win.frame(),0))
    def close():
        if getattr(app,'closing',False):return
        if app.busy:return app.dialog('正在修复','请等待当前操作结束后再关闭。','error')
        app.closing=True
        alpha=float(win.attributes('-alpha'))
        app.ease('window',lambda t:win.attributes('-alpha',alpha*(1-t)),win.destroy,seconds=.18,motion='window')
    win.protocol('WM_DELETE_WINDOW',close)
    def minimize():
        user.ShowWindow(handle(),6)
    bar=ttk.Frame(win,style='Cap.TFrame',padding=(14,5))
    bar.pack(fill='x')
    name=ttk.Label(bar,text='◈   Fabric Medic',style='Cap.TLabel')
    app.logo=name
    name.pack(side='left',padx=(0,2))
    arrow=tk.Canvas(bar,width=32,height=30,highlightthickness=0,bd=0,cursor='hand2')
    arrow.pack(side='left',padx=(0,12))
    arrow.create_line(8,12,16,19,24,12,width=2,tags='chevron')
    app.loader_arrow=arrow
    app.loader_arrow_angle=0.0

    def draw_chevron(deg):
        # 和 PCL 一样：绕自身中心旋转，0° 朝下，180° 朝上
        cx,cy=16.0,15.0
        a=math.radians(deg)
        ca,sa=math.cos(a),math.sin(a)
        pts=[]
        for px,py in ((8,12),(16,19),(24,12)):
            dx,dy=px-cx,py-cy
            pts.extend((cx+dx*ca-dy*sa, cy+dx*sa+dy*ca))
        arrow.coords('chevron',*pts)

    def spin(to,done=None):
        start=app.loader_arrow_angle
        def step(t):
            app.loader_arrow_angle=start+(to-start)*t
            draw_chevron(app.loader_arrow_angle)
        app.ease('loader_arrow',step,done or (lambda:None),motion='page',seconds=0.2)
    popup=None

    def dismiss(event=None):
        nonlocal popup
        if popup is not None:
            job=app.anim.pop('loader_menu',None)
            if job:
                try:app.win.after_cancel(job)
                except Exception:pass
            try:popup.destroy()
            except Exception:pass
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

        # 用独立窗口 + 透明色，才能有真正的圆角（子控件裁不了）
        KEY='#010203'
        W,ROW,PAD=214,46,7
        rows_def=[('fabric','Fabric 模组与依赖'),('forge','Forge 模组与依赖')]
        H=PAD*2+ROW*len(rows_def)

        pop=tk.Toplevel(win)
        pop.overrideredirect(True)
        pop.transient(win)
        pop.configure(bg=KEY)
        try:
            pop.attributes('-transparentcolor',KEY)
        except Exception:
            pop.configure(bg=side)
        canvas=tk.Canvas(pop,width=W,height=H,bg=KEY,highlightthickness=0,bd=0)
        canvas.pack()
        popup=canvas
        app.loader_menu_panel=canvas

        def choose(mode):
            if mode!=app.loader and (getattr(app,'proposed',set()) or getattr(app,'off',set())!=getattr(app,'initial_off',set())):
                dismiss()
                if not app.dialog('切换加载器','放弃当前未应用方案并重新扫描？'):return
            else:dismiss()
            app.loader=mode
            app.prefs['loader']=mode
            app.persist()
            name.configure(text='◈   '+mode.title()+' Medic')
            app.safe(app.scan)

        def rounded(x0,y0,x1,y1,r,fill,tags=''):
            canvas.create_arc(x0,y0,x0+2*r,y0+2*r,start=90,extent=90,fill=fill,outline=fill,tags=tags)
            canvas.create_arc(x1-2*r,y0,x1,y0+2*r,start=0,extent=90,fill=fill,outline=fill,tags=tags)
            canvas.create_arc(x0,y1-2*r,x0+2*r,y1,start=180,extent=90,fill=fill,outline=fill,tags=tags)
            canvas.create_arc(x1-2*r,y1-2*r,x1,y1,start=270,extent=90,fill=fill,outline=fill,tags=tags)
            canvas.create_rectangle(x0+r,y0,x1-r,y1,fill=fill,outline=fill,tags=tags)
            canvas.create_rectangle(x0,y0+r,x1,y1-r,fill=fill,outline=fill,tags=tags)

        hot=[None]
        def paint(hover=None):
            canvas.delete('all')
            rounded(0,0,W-1,H-1,10,side,'bg')
            for i,(mode,details) in enumerate(rows_def):
                y=PAD+i*ROW
                tag='row%d'%i
                if mode==app.loader or hover==i:
                    rounded(4,y,W-5,y+ROW-2,7,sel if mode==app.loader else '#2a3745',tag)
                canvas.create_text(14,y+13,text=mode.title(),anchor='w',
                                   fill=fg,font=('Microsoft YaHei UI',10,'bold'),tags=tag)
                canvas.create_text(14,y+30,text=details,anchor='w',
                                   fill=muted,font=('Microsoft YaHei UI',8),tags=tag)
                if mode==app.loader:
                    canvas.create_text(W-18,y+20,text='✓',anchor='e',
                                       fill=accent,font=('Microsoft YaHei UI',11),tags=tag)
                canvas.tag_bind(tag,'<Button-1>',lambda e,m=mode:choose(m))

        def on_motion(e):
            # 只在行号变化时重绘，避免 Enter/Leave 造成的重绘死循环
            idx=None
            if PAD<=e.y<PAD+ROW*len(rows_def):
                idx=min(len(rows_def)-1,(e.y-PAD)//ROW)
            if idx!=hot[0]:
                hot[0]=idx
                paint(idx)

        canvas.bind('<Motion>',on_motion)
        canvas.bind('<Leave>',lambda e:paint(None) if hot[0] is not None else None)
        paint()

        x=name.winfo_rootx()
        y=bar.winfo_rooty()+bar.winfo_height()+3
        pop.geometry('%dx%d+%d+%d'%(W,H,x,y))
        pop.lift()

        # 和实例切换、页面切换同一套弹簧
        unit=lambda n:max(0.0,min(1.0,n))
        total=420
        def frame(clock):
            if popup is not canvas:
                return
            age=clock*total
            q=unit(age/350)
            dy=-5*(1-unit(age/250))**3-11*(1-q)**1.5*math.cos(1.5*math.pi*q)
            pop.geometry('%dx%d+%d+%d'%(W,H,x,round(y+dy)))
        app.ease('loader_menu',frame,motion='page',seconds=total/1000)

    name.configure(text='◈   '+app.loader.title()+' Medic',cursor='hand2')
    for target in (name,arrow):
        target.bind('<Button-1>',menu)
    def drag(e):
        if os.name=='nt' and not user.IsZoomed(handle()) and not edge(e):
            user.ReleaseCapture()
            user.SendMessageW(wintypes.HWND(int(win.frame(),0)),0xA1,2,0)
    for w in (bar,):
        w.bind('<ButtonPress-1>',drag)
    for title,cmd in [('工作台',lambda:app.navigate('home')),('设置',lambda:app.navigate('settings')),('输出',app.toggle_drawer)]:
        app.button(bar,title,cmd,caption=True).pack(side='left',padx=3)
    for title,cmd in [('×',close),('－',minimize)]:
        app.button(bar,title,cmd,caption=True,width=4,padx=18,pady=9,
                   font=('Microsoft YaHei UI',11)).pack(side='right',padx=2)
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

