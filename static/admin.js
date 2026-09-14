(() => {
  const filter = document.getElementById('job_filter');
  const rows = [...document.querySelectorAll('.admin-job-row')];
  const details = [...document.querySelectorAll('.admin-job-detail')];
  const pageSize = 10;
  let page = 0;
  const dialog = document.getElementById('log_dialog');
  const output = document.getElementById('log_output');
  const title = document.getElementById('log_title');
  const message = document.getElementById('admin_message');
  const matchingRows = () => {
    const needle = filter.value.trim().toLowerCase();
    return rows.filter(row => !needle || row.dataset.taskId.includes(needle));
  };
  const renderPage = () => {
    const matches = matchingRows();
    const pages = Math.max(1, Math.ceil(matches.length / pageSize));
    page = Math.max(0, Math.min(page, pages - 1));
    rows.forEach(row => { row.hidden = true; });
    details.forEach(row => { row.hidden = true; });
    matches.slice(page * pageSize, (page + 1) * pageSize).forEach(row => { row.hidden = false; });
    document.getElementById('jobs_page').textContent = `${matches.length ? page + 1 : 0} / ${matches.length ? pages : 0} · ${matches.length} jobs`;
    document.getElementById('jobs_previous').disabled = page === 0;
    document.getElementById('jobs_next').disabled = page >= pages - 1;
  };
  filter?.addEventListener('input', () => { page = 0; renderPage(); });
  document.getElementById('jobs_previous')?.addEventListener('click', () => { page--; renderPage(); });
  document.getElementById('jobs_next')?.addEventListener('click', () => { page++; renderPage(); });
  document.querySelectorAll('time[data-epoch]').forEach(time => {
    time.textContent = new Date(Number(time.dataset.epoch) * 1000).toLocaleString();
  });
  document.addEventListener('click', async event => {
    const logButton = event.target.closest('[data-logs]');
    if (logButton) {
      const taskId = logButton.dataset.logs;
      title.textContent = `Job logs · ${taskId}`;
      output.textContent = 'Loading…'; dialog.showModal();
      const response = await fetch(`/admin/jobs/${encodeURIComponent(taskId)}/logs`, {credentials:'same-origin'});
      const data = await response.json();
      output.textContent = (data.logs || []).join('\n') || 'No retained logs.';
      return;
    }
    const deleteButton = event.target.closest('[data-delete]');
    if (!deleteButton || !confirm(`Remove ${deleteButton.dataset.delete} from the waiting queue?`)) return;
    const response = await fetch(`/admin/jobs/${encodeURIComponent(deleteButton.dataset.delete)}/queue`, {
      method:'DELETE', credentials:'same-origin', headers:{'X-Admin-CSRF':window.ADMIN_CSRF}
    });
    const data = await response.json(); message.textContent = data.message || 'Request complete.';
    if (response.ok) {
      const row = deleteButton.closest('tr');
      document.querySelector(`[data-detail-for="${row.dataset.taskId}"]`)?.remove();
      row.remove();
      const rowIndex = rows.indexOf(row);
      if (rowIndex >= 0) rows.splice(rowIndex, 1);
      renderPage();
    }
  });
  const toggleRow = row => {
    const detail = document.querySelector(`[data-detail-for="${row.dataset.taskId}"]`);
    const opening = row.getAttribute('aria-expanded') !== 'true';
    rows.forEach(item => item.setAttribute('aria-expanded', 'false'));
    details.forEach(item => { item.hidden = true; });
    row.setAttribute('aria-expanded', String(opening));
    if (detail) detail.hidden = !opening;
  };
  rows.forEach(row => {
    row.addEventListener('click', event => { if (!event.target.closest('button')) toggleRow(row); });
    row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggleRow(row); } });
  });
  fetch('/admin/users', {credentials:'same-origin'}).then(response => response.json()).then(data => {
    document.getElementById('user_count').textContent = data.count ?? 'Unavailable';
    const list = document.getElementById('admin_user_list');
    if (data.status !== 'ok') { list.innerHTML = '<p>The Cognito directory is currently unavailable.</p>'; return; }
    list.innerHTML = data.users.map(user => `<div><span>${escapeHtml(user.email || 'Email unavailable')}</span><small>${escapeHtml(user.status)} · ${user.enabled ? 'enabled' : 'disabled'}</small></div>`).join('') || '<p>No signed-up users.</p>';
  }).catch(() => { document.getElementById('user_count').textContent = 'Unavailable'; });
  const escapeHtml = value => String(value).replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
  renderPage();
})();
