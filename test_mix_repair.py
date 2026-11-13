import json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import Mock
from core import metadata,matches,FabricRule,LookupControl,analyze,install_verified,restore
from repair import build_plan

class MixRepairTests(unittest.TestCase):
    def test_fabric_semantics_remain_separate_from_forge(self):
        for version,rule,result in [('1.20.1','>=1.20-beta.1',True),('1.0.0-beta.4','^1.0.0-beta.4',True),('1.0.0-beta.3','>=1.0.0-beta.4',False),('1.20-2.16.39','>=1.20-2.16.26',True),('2.0.0-beta.1','^1.0.0',False),('1.2.0-alpha','1.2.x',True)]:
            self.assertEqual(matches(version,FabricRule(rule)),result)
        self.assertIsNone(matches('1.20.1','>=1.20-beta.1'))

    def test_bridge_replacement_install_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);mods=root/'mods';mods.mkdir();stage=root/'stage';stage.mkdir()
            original=mods/'api.jar'
            with zipfile.ZipFile(original,'w') as z:z.writestr('fabric.mod.json',json.dumps({'schemaVersion':1,'id':'fabric-api','version':'0.92.11'}))
            bridge=stage/'bridge.jar'
            with zipfile.ZipFile(bridge,'w') as z:z.writestr('META-INF/mods.toml','[[mods]]\nmodId="fabric_api"\nversion="0.92.6"\nprovides=["fabric-api","fabric"]')
            connector=stage/'connector.jar'
            with zipfile.ZipFile(connector,'w') as z:z.writestr('META-INF/mods.toml','[[mods]]\nmodId="connectormod"\nversion="1.0"')
            active={original:metadata(original,'mix')};before=original.read_bytes()
            def resolver(target,*args,**kwargs):
                p=bridge if target=='fabric_api' else connector
                return p,metadata(p,'mix')
            found,errors,swaps=build_plan(active,'1.20.1',stage,resolver,LookupControl(),loader='mix')
            self.assertFalse(errors);self.assertEqual(swaps,{original:bridge})
            self.assertEqual(original.read_bytes(),before)
            batch=install_verified(mods,swaps,found,{},'1.20.1','mix')
            self.assertFalse(original.exists());self.assertTrue((mods/bridge.name).exists())
            restore(mods,batch);self.assertEqual(original.read_bytes(),before)

    def test_existing_bridge_api_needs_no_duplicate_download(self):
        old=Path('original.jar');bridge=Path('bridge.jar');connector=Path('connector.jar')
        active={old:[{'id':'fabric-api','version':'1','depends':{'fabric_api':'*'}}],bridge:[{'id':'fabric_api','version':'1'}],connector:[{'id':'connector','version':'1'}]}
        resolver=Mock(side_effect=AssertionError('unexpected download'))
        found,errors,swaps=build_plan(active,'1.20.1',Path('.'),resolver,LookupControl(),loader='mix')
        self.assertFalse(errors);self.assertFalse(found);self.assertEqual(swaps,{old:bridge})

    def test_forge_wildcard(self):
        from forge import requirement
        self.assertEqual(requirement('*'),'*')
        self.assertTrue(matches('1.0',requirement('*')))

    def test_default_deadline_and_cancel(self):
        c=LookupControl();self.assertEqual(c.deadline,float('inf'));c.check();c.cancelled.set()
        from core import JobStopped
        with self.assertRaises(JobStopped):c.check()

if __name__=='__main__':unittest.main()
