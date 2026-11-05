import io
import re
import tomllib
import zipfile
import json


def requirement(value):
    value=str(value).strip()
    if not value:return '*'
    if value.startswith('[') and value.endswith(']') and ',' not in value:return value[1:-1]
    groups=re.findall(r'([\[(])([^\[\]()]*?)([\])])',value)
    if not groups:
        return '* ' if re.fullmatch(r'[0-9]+(?:\.[0-9]+)*',value) else 'unknown:'+value
    result=[]
    for left,body,right in groups:
        if ',' not in body:
            result.append(body)
            continue
        low,high=map(str.strip,body.split(',',1))
        result.append(' '.join(filter(None,[(('>=' if left=='[' else '>')+low) if low else '',(('<=' if right==']' else '<')+high) if high else ''])) or '*')
    return result


def read(source,depth=0,budget=None):
    if budget is None:budget=[128<<20]
    with zipfile.ZipFile(source) as z:
        def load(name):
            size=z.getinfo(name).file_size
            budget[0]-=size
            if budget[0]<0 or depth>8:raise ValueError('Forge 元数据超过扫描限制')
            return z.read(name)
        if 'META-INF/mods.toml' not in z.namelist():return []
        doc=tomllib.loads(load('META-INF/mods.toml').decode('utf-8-sig'))
        mods=[]
        for entry in doc['mods']:
            key=entry['modId']
            version=str(entry.get('version','?'))
            if version=='${file.jarVersion}' and 'META-INF/MANIFEST.MF' in z.namelist():
                found=re.search(r'(?im)^Implementation-Version: ([^\r\n]+)',load('META-INF/MANIFEST.MF').decode('utf8','replace'))
                if found:version=found[1]
            m=dict(id=key,version=version,depends={},breaks={},conflicts={})
            m['provides']=entry.get('provides',[])
            for d in doc.get('dependencies',{}).get(key,[]):
                target=d['modId']
                if target=='forge' or d.get('side')=='SERVER':continue
                kind=d.get('type','required' if d.get('mandatory',True) else 'optional')
                field={'required':'depends','incompatible':'breaks','discouraged':'conflicts'}.get(kind)
                if field:m[field][target]=requirement(d.get('versionRange',''))
            mods.append(m)
        if 'META-INF/jarjar/metadata.json' in z.namelist():
            for jar in json.loads(load('META-INF/jarjar/metadata.json')).get('jars',[]):
                mods.extend(read(io.BytesIO(load(jar['path'])),depth+1,budget))
        return mods
