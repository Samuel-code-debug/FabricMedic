import sys,tempfile,json,zipfile,time,os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from discovery import discover,inspect_instance
from main import App
from core import metadata,restore,backup_root
import tkinter as tk
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp); instance=root/'.minecraft'/'versions'/'custom-name'; mods=instance/'mods';mods.mkdir(parents=True)
    (instance/'custom-name.json').write_text(json.dumps({'clientVersion':'1.20.1','libraries':[{'name':'net.fabricmc:fabric-loader:0.16.0'}]}))
    assert discover(roots=[root])[0]['version']=='1.20.1'
    assert inspect_instance(mods)['loader']=='fabric'
    def jar(path,ident,version,depends=None):
        with zipfile.ZipFile(path,'w') as z:z.writestr('fabric.mod.json',json.dumps({'schemaVersion':1,'id':ident,'version':version,'depends':depends or {}}))
    jar(mods/'owner.jar','owner','1.0',{'dep':'>=2'})
    jar(mods/'dep.jar','dep','1.0')
    with patch.dict(os.environ,{'LOCALAPPDATA':str(root/'prefs')}):
        win=tk.Tk();win.withdraw();app=App(win);app.folder=mods;app.game.set('1.20.1');app.scan()
        original={p.name:p.read_bytes() for p in mods.glob('*.jar')}
        def candidate(*args,**kwargs):
            file=Path(app.temp.name)/'dep-new.jar';jar(file,'dep','2.0');return file,metadata(file)
        with patch('main.resolve',side_effect=candidate):
            app.prepare_repair();deadline=time.monotonic()+10
            while app.busy and time.monotonic()<deadline:win.update();time.sleep(.02)
        assert not app.busy and app.proposed
        assert original=={p.name:p.read_bytes() for p in mods.glob('*.jar')},'preview wrote to instance'
        with patch.object(app,'dialog',return_value=True):app.commit()
        assert (mods/'dep-new.jar').exists() and not (mods/'dep.jar').exists()
        batch=next(p for p in backup_root(mods).iterdir() if p.is_dir());restore(mods,batch)
        assert original=={p.name:p.read_bytes() for p in mods.glob('*.jar')}
        for page in ['settings','home','version','home']:app.navigate(page);win.update()
        win.destroy()
print('PASS discovery, loader detection, preview no writes, confirmed apply, backup restore, page navigation')
