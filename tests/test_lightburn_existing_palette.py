import ast, hashlib, unittest
from pathlib import Path
from io import BytesIO
from unittest.mock import Mock
from xml.etree import ElementTree as ET
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]

class ExistingLightBurnPaletteTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / 'serverless_api/handler.py').read_text(encoding='utf-8'))
        names = {'append_imported_swatches', 'single_palette_material', 'validate_library_descriptions', 'finalize_import'}
        self.scope = {'ET': ET, 'deepcopy': deepcopy, 'MAX_MATERIAL_BYTES': 4096, 'BUCKET': 'test',
                      'time': Mock(time=lambda: 123), 'dynamo_value': lambda x:x,
                      'material_summary': lambda x: {'count': len(ET.fromstring(x).findall('./Material/Entry'))},
                      'public_library_summary': lambda x:x, 'response': lambda status,body:(status,body)}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'handler','exec'), self.scope)
        self.library = {'library_id':'target','s3_key':'existing.clb','library_intent':'color_palette','name':'Keep name'}
        self.scope['owned_material'] = Mock(return_value=self.library)
        self.scope['s3'] = Mock()
        self.scope['table'] = Mock()
        self.original = b'<LightBurnLibrary><Material name="Steel"><Entry Desc="Blue"><CutSetting type="Scan"><speed Value="40"/></CutSetting></Entry></Material></LightBurnLibrary>'
        self.scope['s3'].get_object.return_value = {'Body':BytesIO(self.original), 'ETag':'"version-one"'}
        self.incoming = b'<LightBurnLibrary><Material name="Imported"><Entry Desc="Red" RasterizerLightBurnSource="source"><CutSetting type="Scan"><speed Value="20"/><SubLayer type="Cut"/></CutSetting></Entry></Material></LightBurnLibrary>'

    def append(self):
        return self.scope['append_imported_swatches']('owner','target',self.incoming)

    def test_append_preserves_existing_settings_and_target_identity(self):
        status, result = self.append()
        self.assertEqual(status,200)
        self.assertEqual(result['material_library']['library_id'],'target')
        args=self.scope['s3'].put_object.call_args.kwargs
        self.assertEqual(args['IfMatch'],'"version-one"')
        root=ET.fromstring(args['Body'])
        self.assertEqual(root.find('./Material').get('name'),'Steel')
        self.assertEqual(root.find('./Material/Entry/CutSetting/speed').get('Value'),'40')
        self.assertEqual(len(root.findall('./Material/Entry')),2)
        self.assertEqual(root.findall('./Material/Entry')[1].get('RasterizerLightBurnSource'),'source')
        self.assertIsNotNone(root.find('./Material/Entry[2]/CutSetting/SubLayer'))
        self.scope['table'].put_item.assert_not_called()

    def test_missing_or_wrong_type_target_cannot_be_modified(self):
        for value in [None, dict(self.library,library_intent='hatch_palette'),dict(self.library,library_intent='processing_palette')]:
            self.scope['owned_material'].return_value=value
            with self.assertRaises(ValueError): self.append()
        self.scope['s3'].put_object.assert_not_called()

    def test_duplicate_description_rejected_before_write(self):
        self.incoming=self.incoming.replace(b'Desc="Red"',b'Desc="Blue"')
        with self.assertRaises(ValueError): self.append()
        self.scope['s3'].put_object.assert_not_called()

    def test_concurrent_object_change_does_not_update_summary_or_retry(self):
        self.scope['s3'].put_object.side_effect=RuntimeError('precondition failed')
        with self.assertRaises(RuntimeError): self.append()
        self.assertEqual(self.scope['s3'].put_object.call_count,1)
        self.scope['table'].update_item.assert_not_called()

    def test_finalizing_target_import_routes_to_append_and_consumes_session(self):
        import secrets, uuid, json
        class ClientError(Exception): pass
        self.scope.update(user_id=lambda event:'owner', body_json=lambda event:event,
                          secrets=secrets, uuid=uuid, json=json, ClientError=ClientError,
                          token_hash=lambda token:token, retain_selected_material=lambda contents,name:contents)
        self.scope['table'].get_item.return_value={'Item':{'kind':'material','capability':'token','s3_key':'upload','target_library_id':'target','material_name':'Imported'}}
        self.scope['s3'].get_object.return_value={'Body':BytesIO(self.incoming),'ContentLength':len(self.incoming),'Metadata':{'upload-capability':'token'}}
        self.scope['append_imported_swatches']=Mock(return_value=(200,{'ok':True}))
        result=self.scope['finalize_import']({'upload_token':'token'},'session')
        self.assertEqual(result,(200,{'ok':True}))
        self.scope['append_imported_swatches'].assert_called_once_with('owner','target',self.incoming)
        self.scope['table'].put_item.assert_not_called()
        self.scope['table'].delete_item.assert_called_once()
        self.scope['s3'].delete_object.assert_called_once_with(Bucket='test',Key='upload')

    def test_combined_size_limit_rejects_before_write(self):
        self.scope['MAX_MATERIAL_BYTES']=len(self.original)+10
        with self.assertRaisesRegex(ValueError,'size limit'): self.append()
        self.scope['s3'].put_object.assert_not_called()
