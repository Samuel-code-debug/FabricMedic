import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from core import metadata, analyze, matches, LookupControl, JobStopped, fetch, resolve


def jar(entries):
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w') as z:
        for name,data in entries.items():z.writestr(name,data)
    result.seek(0)
    return result

class DiagnosticsTests(unittest.TestCase):
    def test_mix_bridge_requirements(self):
        m=metadata(jar({'fabric.mod.json':json.dumps({'schemaVersion':1,'id':'example','version':'1'})}),'mix')
        self.assertEqual(set(analyze({Path('a.jar'):m},'1.20.1')[1]),{'connector','fabric_api'})

    def test_connector_manifest_before_jarjar(self):
        m=metadata(jar({'META-INF/jarjar/metadata.json':'{"jars":[]}',
            'META-INF/services/cpw.mods.modlauncher.api.ITransformationService':'x',
            'META-INF/MANIFEST.MF':'Automatic-Module-Name: org.sinytra.connector\nImplementation-Version: 1.0\n'}),'mix')
        self.assertIn('connectormod',m[0]['provides'])
        self.assertIn('fabric_api',m[0]['depends'])

    def test_connector_toml_alias(self):
        m=metadata(jar({'META-INF/mods.toml':'[[mods]]\nmodId="connectormod"\nversion="1"'}),'mix')
        self.assertIn('connector',m[0]['provides'])
        self.assertIn('fabric_api',m[0]['depends'])

    def test_description_newlines(self):
        data='{"schemaVersion":1,"id":"betterend","version":"4.0.11","description":"line one\nline two"}'
        self.assertEqual(metadata(jar({'fabric.mod.json':data}))[0]['id'],'betterend')
    def test_forge_library_nested_mod_and_optional_server(self):
        child=jar({'META-INF/mods.toml':'''[[mods]]
modId="kotlinforforge"
version="4.12.0"
[[dependencies.kotlinforforge]]
modId="optional"
mandatory=false
versionRange="[1,)"
[[dependencies.kotlinforforge]]
modId="serveronly"
mandatory=true
side="SERVER"
versionRange="[1,)"
'''})
        parent=jar({'META-INF/jarjar/metadata.json':json.dumps({'jars':[{'path':'lib.jar'}]}),'lib.jar':child.getvalue()})
        mods=metadata(parent,'mix')
        self.assertEqual(mods[0]['id'],'kotlinforforge')
        self.assertEqual(mods[0]['depends'],{})
    def test_unknown_not_repair_warning_not_conflict(self):
        a={Path('a.jar'):[{'id':'a','version':'1','depends':{'lib':'>=1.20-Forge-4.0.1'},'conflicts':{'lib':'*'}}],Path('lib.jar'):[{'id':'lib','version':'1.20-Forge-4.0.2'}]}
        repairs={};issues=[]
        pairs,missing,notes=analyze(a,'1.20.1',repairs,issues)
        self.assertFalse(pairs or missing or repairs)
        self.assertEqual({x['level'] for x in issues},{'review','info'})
        self.assertIsNone(matches('1.20.1','>=1.20-beta'))
    def test_known_bad_and_missing_still_reported(self):
        a={Path('a.jar'):[{'id':'a','version':'1','depends':{'lib':'>=2','missing':'*'}}],Path('lib.jar'):[{'id':'lib','version':'1'}]}
        repairs={};issues=[]
        _,missing,_=analyze(a,'1.20.1',repairs,issues)
        self.assertIn('missing',missing);self.assertIn('lib',repairs)
        self.assertTrue(all(i['level']=='error' for i in issues))
    def test_group_duplicate_unknown_requirements(self):
        mods={Path(str(i)+'.jar'):[{'id':str(i),'version':'1','depends':{'lib':'>=1-Forge-2'}}] for i in range(12)}
        mods[Path('lib.jar')]=[{'id':'lib','version':'1-Forge-3'}]
        self.assertEqual(len(analyze(mods,'1.20.1')[2]),1)
    def test_cancel_and_deadline_prevent_network(self):
        for control in (LookupControl(seconds=-1),LookupControl()):
            if control.deadline>0:control.cancelled.set()
            with patch('core.urlopen') as open_url:
                with self.assertRaises(JobStopped):fetch('https://example.com',100,control)
                open_url.assert_not_called()
        with self.assertRaises(JobStopped):LookupControl(seconds=-1).check()
    def test_cancel_during_read_stops_next_read(self):
        control=LookupControl()
        class Response:
            count=0
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read1(self,size):
                self.count+=1;control.cancelled.set();return b'abc'
        r=Response()
        with patch('core.urlopen',return_value=r):
            with self.assertRaises(JobStopped):fetch('https://example.com',100,control)
        self.assertEqual(r.count,1)
    def test_network_error_is_not_no_candidate(self):
        with patch('core.urlopen',side_effect=TimeoutError('timeout')):
            with self.assertRaisesRegex(RuntimeError,'网络请求失败'):fetch('https://example.com',100)

if __name__=='__main__':unittest.main()
