import ast
import hashlib
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def test_generated_palette_uses_existing_vault_parser_and_retains_source_snapshot():
    script = """
      import {buildPaletteImport} from './serverless_web/lightburn-palette-model.js';
      const source={units:{units:'mm/min',distance_units:'in'},library:{name:'Live',entries:[
        {guid:'one',material:'Steel',description:'Blue',cut:{kind:'normal',mode:'scan',params:{speed:600,interval:0.01,frequency:200000,q_pulse_width:100}}},
        {guid:'two',material:'Brass',description:'Blue',cut:{kind:'normal',mode:'cut',params:{speed:1200,max_power:20}}}
      ]}};
      process.stdout.write(buildPaletteImport(source,[0,1],'Imported palette').xml);
    """
    contents = subprocess.check_output(['node', '--input-type=module', '-e', script], cwd=ROOT)
    tree = ast.parse((ROOT / 'serverless_api/handler.py').read_text(encoding='utf-8'))
    names = {'effective_lightburn_settings', 'lightburn_entry_path', 'lightburn_entry_ref', 'material_summary', 'retain_selected_material'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    scope = {'ET': ET, 'hashlib': hashlib}
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'handler.py', 'exec'), scope)
    retained = scope['retain_selected_material'](contents, 'Imported palette')
    summary = scope['material_summary'](retained)
    assert len(summary['entries']) == 2
    settings = summary['entries'][0]['settings']
    assert float(settings['speed']) == 10
    assert float(settings['interval']) == 0.254
    assert float(settings['frequency']) == 200000
    assert float(settings['QPulseWidth']) == 100
    source = json.loads(ET.fromstring(retained).find('./Material/Entry').get('RasterizerLightBurnSource'))
    assert source['entry']['material'] == 'Steel'
    assert source['entry']['guid'] == 'one'

def test_processing_import_roles_resolve_against_real_backend_entry_references():
    script = """
      import {buildProcessingImport} from './serverless_web/lightburn-processing-model.js';
      const snapshot={units:{units:'mm/s',distance_units:'mm'},library:{name:'Live',entries:[
        {material:'Steel',description:'Shared',cut:{kind:'normal',mode:'scan',params:{speed:10}}},
        {material:'Brass',description:'Shared',cut:{kind:'normal',mode:'cut',params:{speed:20}}}
      ]}};
      process.stdout.write(JSON.stringify(buildProcessingImport(snapshot,{Cut:'1',Score:'1',Fill:'0'},'Processing',['Cut','Score','Photo','Fill'])));
    """
    preview = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', script], cwd=ROOT))
    tree = ast.parse((ROOT / 'serverless_api/handler.py').read_text(encoding='utf-8'))
    names = {'effective_lightburn_settings', 'lightburn_entry_path', 'lightburn_entry_ref', 'material_summary', 'retain_selected_material'}
    scope = {'ET': ET, 'hashlib': hashlib}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'handler.py','exec'),scope)
    summary=scope['material_summary'](scope['retain_selected_material'](preview['xml'].encode(),'Processing'))
    mapping_script = """
      import {processingRoleMapping} from './serverless_web/lightburn-processing-model.js';
      let input=''; for await (const chunk of process.stdin) input+=chunk;
      const {preview,summary}=JSON.parse(input);
      process.stdout.write(JSON.stringify(processingRoleMapping(preview,summary)));
    """
    result=subprocess.run(['node','--input-type=module','-e',mapping_script],input=json.dumps({'preview':preview,'summary':summary}),capture_output=True,text=True,cwd=ROOT,check=True)
    roles=json.loads(result.stdout)['materials']['Processing']
    assert roles['Cut'] == roles['Score']
    assert roles['Fill'] != roles['Cut']
    assert roles['Photo'] == ''
    assert roles['Cut'].startswith('setting:')
