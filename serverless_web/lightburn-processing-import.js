import {buildProcessingImport, processingRoleMapping} from './lightburn-processing-model.js';

export function installProcessingImport({api, upload, reload, roles, send}) {
  let button, panel, saving = false;
  function setEnabled(enabled) {
    if (!enabled) {button?.remove(); button = null; panel?.close(); panel?.remove(); panel = null; return;}
    if (button) return;
    button = document.createElement('button'); button.type = 'button';
    button.dataset.lightburnProcessingImport = ''; button.textContent = 'Import processing palette from LightBurn';
    document.querySelector('#materialImport').after(button);
    button.onclick = open;
  }
  function open() {
    if (saving || panel) return;
    const dialog = document.createElement('dialog'); panel = dialog;
    dialog.className = 'lightburn-dialog lightburn-palette-dialog';
    dialog.setAttribute('aria-labelledby', 'lb-processing-heading');
    dialog.innerHTML = '<h2 id="lb-processing-heading">Import processing palette from LightBurn</h2><p>Read the selected LightBurn library, then choose a setting for each processing role. Roles can remain unassigned. A setting used for multiple roles is imported once.</p><button type="button" data-proc-read>Read selected library</button><label>Palette name <input data-proc-name maxlength="160"></label><div data-proc-roles></div><button type="button" data-proc-preview disabled>Preview import</button><div data-proc-details></div><label data-proc-warning hidden><input type="checkbox" data-proc-ack> I reviewed the fields retained for reference only, not applied as settings.</label><p data-proc-status role="status" aria-live="polite" tabindex="-1"></p><button type="button" data-proc-save disabled>Create processing palette</button><button type="button" data-proc-close>Close</button>';
    const find = key => dialog.querySelector(`[data-proc-${key}]`);
    let snapshot, preview, choices = {};
    const status = find('status'), name = find('name'), save = find('save'), ack = find('ack');
    function invalidate() {
      preview = null; ack.checked = false; save.disabled = true;
      find('details').replaceChildren(); find('warning').hidden = true;
      find('preview').disabled = !snapshot || !name.value.trim() || !Object.values(choices).some(value => value !== '');
    }
    name.oninput = invalidate;
    ack.onchange = () => {save.disabled = !preview || saving || (preview.warnings.length > 0 && !ack.checked);};
    find('close').onclick = () => {if (!saving) dialog.close();};
    dialog.oncancel = event => {if (saving) event.preventDefault();};
    dialog.onclose = () => {dialog.remove(); if (panel === dialog) panel = null; button?.focus();};
    find('read').onclick = async () => {
      snapshot = null; choices = {}; find('roles').replaceChildren(); invalidate();
      find('read').disabled = true; status.textContent = 'Reading selected LightBurn library...';
      try {
        const received = await send('readPaletteLibrary');
        if (panel !== dialog) return;
        snapshot = received; name.value ||= `${snapshot.library.name || 'LightBurn'} processing`;
        for (const role of roles) {
          choices[role] = '';
          const label = document.createElement('label'); label.textContent = role;
          const search = document.createElement('input'); search.type = 'search'; search.placeholder = `Find a setting for ${role}`; search.setAttribute('aria-label', `Find a setting for ${role}`);
          const select = document.createElement('select'); select.dataset.procRole = role; select.setAttribute('aria-label', `${role} setting`);
          function options() {
            select.replaceChildren(new Option('Unassigned', ''));
            snapshot.library.entries.forEach((entry, index) => {
              const text = `${entry.material || 'Unnamed material'} - ${entry.description || 'Unnamed setting'} (${entry.cut.kind === 'image' ? 'image' : entry.cut.mode})`;
              if (String(index) === choices[role] || text.toLowerCase().includes(search.value.toLowerCase())) select.add(new Option(text, String(index)));
            });
            select.value = choices[role];
          }
          search.oninput = options;
          select.onchange = () => {choices[role] = select.value; invalidate();};
          options(); label.append(search, select); find('roles').append(label);
        }
        invalidate();
        status.textContent = snapshot.library.entries.length ? `${snapshot.library.entries.length} settings available. Assign at least one role, then preview.` : 'The selected library is empty. Choose a populated library in LightBurn and read again.';
      } catch (error) {status.textContent = error.message;}
      finally {find('read').disabled = false;}
    };
    find('preview').onclick = () => {
      try {
        preview = buildProcessingImport(snapshot, choices, name.value, roles);
        const details = find('details'); details.replaceChildren();
        const conversion = document.createElement('p'); conversion.textContent = preview.conversions; details.append(conversion);
        for (const [role, description] of Object.entries(preview.roleDescriptions)) {
          const row = document.createElement('p'); row.textContent = `${role}: ${description || 'Unassigned'}`; details.append(row);
        }
        for (const entry of preview.entries) {
          const detail = document.createElement('details'), heading = document.createElement('summary'), settings = document.createElement('pre');
          heading.textContent = `${entry.material} - ${entry.description}`;
          settings.textContent = JSON.stringify({type: entry.type, settings: entry.settings, subLayers: entry.subLayers}, null, 2);
          detail.append(heading, settings); details.append(detail);
        }
        const warnings = document.createElement('pre'); warnings.textContent = preview.warnings.join('\n'); details.append(warnings);
        find('warning').hidden = !preview.warnings.length; ack.checked = false;
        save.disabled = preview.warnings.length > 0;
        status.textContent = `Preview ready: ${preview.entries.length} unique settings. Nothing has been saved.`;
      } catch (error) {preview = null; save.disabled = true; status.textContent = error.message;}
    };
    save.onclick = async () => {
      if (!preview || saving || (preview.warnings.length && !ack.checked)) return;
      saving = true;
      for (const control of dialog.querySelectorAll('button,input,select')) control.disabled = true;
      status.textContent = 'Creating processing palette...'; status.scrollIntoView({block:'nearest'});
      let finalizing = false, created = false, assigned = false;
      try {
        const file = new File([preview.xml], 'lightburn-processing.clb', {type:'application/xml'});
        const grant = await api('/account/imports', {method:'POST', body:JSON.stringify({kind:'material',filename:file.name,name:preview.name,material_name:preview.materialName,library_intent:'processing_palette'})});
        await upload(file, grant.upload); finalizing = true;
        const result = await api(`/account/imports/${grant.import_id}/finalize`, {method:'POST',body:JSON.stringify({upload_token:grant.upload_token})});
        created = true; status.textContent = 'Palette created. Saving processing roles...';
        const saved = result.material_library;
        if (!saved?.library_id) throw new Error('The saved palette identity is missing.');
        const mapping = processingRoleMapping(preview, saved);
        const latest = await api('/account/resources');
        await api('/account/preferences', {method:'PATCH',body:JSON.stringify({processing_palette_role_assignments:{...(latest.preferences?.processing_palette_role_assignments || {}),[saved.library_id]:mapping}})});
        assigned = true; await reload();
        status.textContent = 'Processing palette created with your role assignments. Review it in the Vault.';
      } catch (error) {
        status.textContent = created ? assigned ? 'Palette and roles saved, but the Vault could not refresh. Refresh this page.' : 'Palette created, but role assignments could not be confirmed. Do not import again. Refresh the Vault and review its roles.' : finalizing ? 'The save result could not be confirmed. Refresh the Vault and check for the palette before importing again.' : `Import stopped: ${error.message}. Close and reopen this dialog to try again.`;
      } finally {
        saving = false; preview = null; find('close').disabled = false;
        save.textContent = created ? 'Palette created' : 'Import stopped'; find('close').textContent = 'Done';
        status.focus({preventScroll:true}); status.scrollIntoView({block:'nearest'});
      }
    };
    document.body.append(dialog); dialog.showModal();
  }
  return {setEnabled};
}
