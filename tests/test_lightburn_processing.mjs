import test from 'node:test';
import assert from 'node:assert/strict';
import {buildProcessingImport, processingRoleMapping} from '../serverless_web/lightburn-processing-model.js';
const roles = ['Cut','Score','Photo','Fill','Shovel','Cleaning','3D-Slice'];
const snapshot = {units:{units:'mm/s',distance_units:'mm'},library:{name:'Library',entries:[
 {material:'Steel',description:'Same',cut:{kind:'normal',mode:'cut',params:{speed:10}}},
 {material:'Brass',description:'Same',cut:{kind:'normal',mode:'scan',params:{speed:20}}},
]}};
test('role-first selection imports only unique settings and keeps blank roles explicit', () => {
 const result=buildProcessingImport(snapshot,{Cut:'0',Score:'0',Fill:'1'},'Processing',roles);
 assert.equal(result.entries.length,2);
 assert.equal(result.roleDescriptions.Cut,result.roleDescriptions.Score);
 assert.notEqual(result.roleDescriptions.Cut,result.roleDescriptions.Fill);
 assert.equal(result.roleDescriptions.Photo,'');
 const mapping=processingRoleMapping(result,{entries:result.entries.map((e,i)=>({description:e.description,entry_ref:`setting:${i}`,material:'Processing'}))});
 assert.equal(mapping.materials.Processing.Cut,'setting:0');
 assert.equal(mapping.materials.Processing.Score,'setting:0');
 assert.equal(mapping.materials.Processing.Photo,'');
});
test('empty, invalid, and unknown role selections fail before saving', () => {
 for (const choices of [{},{Cut:'99'},{Other:'0'},{Cut:'NaN'}]) assert.throws(()=>buildProcessingImport(snapshot,choices,'P',roles));
});
test('missing saved entry identities cannot silently drop role assignments', () => {
 const preview=buildProcessingImport(snapshot,{Cut:'0'},'P',roles);
 assert.throws(()=>processingRoleMapping(preview,{entries:[]}),/saved setting/);
});
