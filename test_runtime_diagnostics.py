import io,json,os,tempfile,time,unittest,zipfile
from pathlib import Path
from core import metadata,analyze,verify_selection,LookupControl
from runtime_diagnostics import attach_runtime_failures
from repair import build_plan

def jar(entries):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for k,v in entries.items():z.writestr(k,v)
    b.seek(0);return b

class RuntimeTests(unittest.TestCase):
    def test_empty_loader_version_blocks_validation(self):
        m=metadata(jar({'META-INF/mods.toml':'modLoader="javafml"\nloaderVersion=""\n[[mods]]\nmodId="test"\nversion="1"'}),'mix')
        repairs={};analyze({Path('test.jar'):m},'1.20.1',repairs)
        self.assertIn('test',repairs)
        with self.assertRaisesRegex(ValueError,'加载语言'):verify_selection({Path('test.jar'):m},set(),'1.20.1')

    def test_log_failure_and_stale_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);mods=root/'mods';mods.mkdir();logs=root/'logs';logs.mkdir()
            p=mods/'broken.jar';p.write_bytes(b'x');log=logs/'latest.log'
            log.write_text('Encountered error while transforming jar file '+str(p),encoding='utf8')
            active={p:[{'id':'broken','version':'1','_platform':'fabric'}]}
            attach_runtime_failures(mods,active);self.assertIn('_runtime_failure',active[p][0])
            active[p][0].pop('_runtime_failure');future=time.time()+10;os.utime(p,(future,future))
            attach_runtime_failures(mods,active);self.assertNotIn('_runtime_failure',active[p][0])

    def test_mixin_failure_is_attributed_to_current_fabric_mod(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);mods=root/'mods';mods.mkdir();(root/'logs').mkdir()
            p=mods/'fast.jar';p.write_bytes(b'x')
            (root/'logs'/'latest.log').write_text('Critical injection failure from mod fast failed injection check',encoding='utf8')
            active={p:[{'id':'fast','version':'1','_platform':'fabric'}]}
            attach_runtime_failures(mods,active)
            self.assertIn('_runtime_failure',active[p][0])

    def test_runtime_repair_requires_native_candidate(self):
        p=Path('broken.jar');candidate=Path('fixed.jar');active={p:[{'id':'broken','version':'1','_runtime_failure':'conversion failed'}]}
        calls=[]
        def resolver(target,*args,**kwargs):
            calls.append(kwargs);return candidate,[{'id':'broken','version':'1','_platform':'forge'}]
        found,errors,swaps=build_plan(active,'1.20.1',Path('.'),resolver,LookupControl(),loader='mix')
        self.assertFalse(errors);self.assertTrue(calls[0]['native_only']);self.assertEqual(swaps[p],candidate)

    def test_forge_prerelease_ranges(self):
        from core import matches
        from forge import requirement
        self.assertTrue(matches('1.20-2.16.39',requirement('[1.20-2.16.26,)')))
        self.assertFalse(matches('1.20-2.16.9',requirement('[1.20-2.16.26,)')))
        self.assertTrue(matches('1.0.0-beta.49+1.20.1',requirement('[1.0.0-beta.18,)')))
        self.assertFalse(matches('1.0.0-beta.17+1.20.1',requirement('[1.0.0-beta.18,)')))
        self.assertIsNone(matches('1.20-Forge-4.0.2',requirement('[1.20-Forge-4.0.1,)')))

    def test_config_port_bundle_preserves_declared_constraints(self):
        old=Path('port.jar');new=Path('extras.jar')
        active={old:[{'id':'forgeconfigapiport','version':'8','_loader_problem':'duplicate package'}]}
        def resolver(*args,**kwargs):return new,[{'id':'connectorextras','version':'1'}, {'id':'forgeconfigapiport','version':'8'}]
        found,errors,swaps=build_plan(active,'1.20.1',Path('.'),resolver,LookupControl(),loader='mix')
        self.assertFalse(errors);self.assertEqual(swaps[old],new)

    def test_config_port_conflict_only_in_mix(self):
        entries={'fabric.mod.json':json.dumps({'schemaVersion':1,'id':'forgeconfigapiport','version':'8.0.3'}),'net/minecraftforge/fml/config/ModConfig.class':b'x'}
        self.assertNotIn('_loader_problem',metadata(jar(entries),'fabric')[0])
        self.assertIn('_loader_problem',metadata(jar(entries),'mix')[0])

if __name__=='__main__':unittest.main()
