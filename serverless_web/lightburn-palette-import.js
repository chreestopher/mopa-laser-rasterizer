import {observeLightBurn} from './lightburn-page-bridge.js';
import {buildPaletteImport, defaultSwatchAssignments, paletteSwatchMapping} from './lightburn-palette-model.js';

export function installPaletteImport({api, upload, reload, getPalette}) {
  if (location.origin !== 'https://serverless-staging.mopa-laser-rasterizer.com') return;
  let button, dialog, snapshot, preview, selected = new Set(), saving = false;
  const bridge = observeLightBurn(enabled => {
    if (!enabled) {button?.remove(); button = null; dialog?.close(); dialog?.remove(); dialog = null; return;}
    if (button) return;
    button = document.createElement('button'); button.type = 'button'; button.dataset.lightburnPaletteImport = ''; button.textContent = 'Import swatch palette from LightBurn';
    document.querySelector('#materialImport').after(button);
    button.onclick = open;
  });
  function open() {
    if (saving) return;
    if (dialog) {dialog.showModal(); return;}
    dialog = document.createElement('dialog'); dialog.className = 'lightburn-dialog lightburn-palette-dialog'; dialog.setAttribute('aria-labelledby', 'lb-palette-heading');
    dialog.innerHTML = '<h2 id="lb-palette-heading">Import swatch palette from LightBurn</h2><p>Select settings from the library currently selected in LightBurn. This creates a new Color palette snapshot; it does not change LightBurn or existing palettes.</p><button type="button" data-lbp-read>Read selected library</button><p role="status" aria-live="polite" data-lbp-status></p><label>Palette name <input data-lbp-name maxlength="160"></label><label>Find settings <input type="search" data-lbp-search></label><div data-lbp-entries class="lightburn-palette-entries"></div><p data-lbp-count>0 selected</p><button type="button" data-lbp-preview disabled>Preview import</button><div data-lbp-preview-details></div><label data-lbp-warning-label hidden><input type="checkbox" data-lbp-ack> I reviewed the fields that will be stored for reference only, not applied as settings.</label><p>After saving, use the Vault’s existing swatch assignments to map these settings to Rasterizer colors. Imported settings keep their source names; no color is guessed.</p><button type="button" data-lbp-save disabled>Create palette</button><button type="button" data-lbp-close>Close</button>';
    document.body.append(dialog); dialog.showModal();
    const panel = dialog;
    const find = key => panel.querySelector(`[data-lbp-${key}]`);
    const status = find('status'), name = find('name'), rows = find('entries'), search = find('search'), save = find('save'), showPreview = find('preview'), ack = find('ack');
    let assignments = [], palette = [];
    function invalidate() {preview = null; save.disabled = true; ack.checked = false; find('preview-details').replaceChildren(); find('warning-label').hidden = true; showPreview.disabled = !selected.size || !name.value.trim() || saving; find('count').textContent = `${selected.size} selected (up to 100)`;}
    name.oninput = invalidate;
    search.oninput = () => {for (const row of rows.children) row.hidden = !row.textContent.toLowerCase().includes(search.value.toLowerCase());};
    ack.onchange = () => {save.disabled = !preview || saving || preview.warnings.length > 0 && !ack.checked;};
    find('close').onclick = () => {if (!saving) dialog.close();};
    dialog.addEventListener('cancel', event => {if (saving) event.preventDefault();});
    find('read').onclick = async () => {
      snapshot = null; selected = new Set(); rows.replaceChildren(); invalidate(); status.textContent = 'Reading selected Material Library…'; find('read').disabled = true;
      try {
        const received = await bridge.send('readPaletteLibrary');
        if (dialog !== panel) return;
        snapshot = received;
        name.value ||= `${snapshot.library.name || 'LightBurn'} palette`;
        snapshot.library.entries.forEach((entry, index) => {
          const row = document.createElement('label'), checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.dataset.lbpEntry = String(index);
          checkbox.onchange = () => {checkbox.checked ? selected.add(index) : selected.delete(index); invalidate();};
          row.append(checkbox, document.createTextNode(`${entry.material || 'Unnamed material'} — ${entry.description || 'Unnamed setting'} (${entry.cut.kind === 'image' ? 'image' : entry.cut.mode})`)); rows.append(row);
        });
        status.textContent = snapshot.library.entries.length ? `${snapshot.library.name || 'Selected library'}: ${snapshot.library.entries.length} settings. Select the entries to import.` : 'This library is empty. Select a populated Material Library in LightBurn and read again.';
        invalidate();
      } catch (error) {if (dialog) status.textContent = error.message;}
      finally {if (dialog === panel) find('read').disabled = false;}
    };
    showPreview.onclick = () => {
      try {
        preview = buildPaletteImport(snapshot, [...selected], name.value);
        const area = find('preview-details'); area.replaceChildren();
        const conversion = document.createElement('p'); conversion.textContent = preview.conversions; area.append(conversion);
        palette = getPalette();
        assignments = defaultSwatchAssignments(preview.entries, palette);
        const pickers = [];
        function updateChoices() {
          for (const [index, picker] of pickers.entries()) {
            for (const option of picker.options) option.disabled = Boolean(option.value && assignments.some((hex, other) => other !== index && hex === option.value));
          }
        }
        for (const [index, entry] of preview.entries.entries()) {
          const label = document.createElement('label'), picker = document.createElement('select');
          label.textContent = `${entry.material} ? ${entry.description}: Rasterizer swatch`;
          picker.dataset.lbpSwatch = String(index);
          picker.add(new Option('Unassigned', ''));
          for (const swatch of palette) picker.add(new Option(`${swatch.name} ? ${swatch.hex}`, swatch.hex.toUpperCase()));
          picker.value = assignments[index];
          picker.onchange = () => {assignments[index] = picker.value; updateChoices();};
          pickers.push(picker); label.append(picker); area.append(label);
          const details = document.createElement('details'), summary = document.createElement('summary'), body = document.createElement('pre');
          summary.textContent = `${entry.material} — ${entry.description}`; body.textContent = JSON.stringify({type: entry.type, settings: entry.settings, subLayers: entry.subLayers}, null, 2); details.append(summary, body); area.append(details);
        }
        updateChoices();
        if (preview.warnings.length) {const notes = document.createElement('pre'); notes.textContent = preview.warnings.join('\n'); area.append(notes);}
        find('warning-label').hidden = !preview.warnings.length; ack.checked = false; save.disabled = preview.warnings.length > 0;
        status.textContent = `Preview ready: ${preview.entries.length} settings. Nothing has been saved.`;
      } catch (error) {preview = null; save.disabled = true; status.textContent = error.message;}
    };
    save.onclick = async () => {
      if (!preview || saving || preview.warnings.length && !ack.checked) return;
      let mapping;
      try {mapping = paletteSwatchMapping(preview.entries, assignments, palette);}
      catch (error) {status.textContent = error.message; return;}
      saving = true; for (const control of dialog.querySelectorAll('button,input,select')) control.disabled = true;
      // Keep progress and results beside the action, even with a long preview.
      save.before(status);
      status.tabIndex = -1;
      status.scrollIntoView({block: 'nearest'});
      save.textContent = 'Creating palette?';
      let finalizing = false, saved = false, mapped = false;
      try {
        status.textContent = 'Saving new palette…';
        const file = new File([preview.xml], 'lightburn-import.clb', {type: 'application/xml'});
        const grant = await api('/account/imports', {method: 'POST', body: JSON.stringify({kind: 'material', filename: file.name, name: preview.name, material_name: preview.materialName, library_intent: 'color_palette'})});
        await upload(file, grant.upload);
        finalizing = true;
        const result = await api(`/account/imports/${grant.import_id}/finalize`, {method: 'POST', body: JSON.stringify({upload_token: grant.upload_token})}); saved = true;
        status.textContent = 'Palette saved. Saving swatch assignments?';
        const libraryId = result.material_library?.library_id;
        if (!libraryId) throw new Error('Saved library identifier missing');
        const latest = await api('/account/resources');
        await api('/account/preferences', {method: 'PATCH', body: JSON.stringify({material_library_color_assignments: {...(latest.preferences?.material_library_color_assignments || {}), [libraryId]: mapping}})});
        mapped = true;
        status.textContent = 'New swatch palette saved. Refreshing the Vault?';
        save.textContent = 'Palette created';
        find('close').textContent = 'Done';
        status.focus({preventScroll: true});
        status.scrollIntoView({block: 'nearest'});
        await reload();
        status.textContent = 'New swatch palette saved with your swatch assignments. Review it in the Vault.';
      } catch (error) {status.textContent = saved ? (mapped ? 'Palette saved with swatch assignments, but the Vault list could not refresh. Refresh this page to see it.' : 'Palette saved, but swatch assignments could not be confirmed. Do not import again. Refresh the Vault and review or set its swatch assignments there.') : finalizing ? 'The save result could not be confirmed. Refresh the Vault and check for the palette before importing again.' : `Import stopped: ${error.message}. Close and reopen this dialog to start a new import.`;}
      finally {
        saving = false; preview = null; find('close').disabled = false;
        if (!saved) save.textContent = 'Import stopped';
        else {save.textContent = 'Palette created'; find('close').textContent = 'Done';}
        status.focus({preventScroll: true});
        status.scrollIntoView({block: 'nearest'});
      }
    };
    panel.addEventListener('close', () => {if (!saving) {panel.remove(); if (dialog === panel) {dialog = null; snapshot = null; preview = null; selected = new Set(); button?.focus();}}});
  }
}
