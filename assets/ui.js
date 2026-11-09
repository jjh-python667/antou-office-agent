'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const token = window.OFFICE_TOKEN;
  const profiles = new Map(), selectedFiles = new Set(), traceMap = new Map();
  const streamedReplies = new Map();
  const emptyState = () => ({session: '', draft: '', messages: [], traces: [], scroll: 0, status: '就绪'});
  const states = {role: emptyState(), agent: emptyState()};
  const toolNames = {list_files: '查看工作文件', read_file: '读取资料', summarize_table: '检查并汇总表格', create_spreadsheet: '生成 Excel', write_document: '生成 Word'};
  let providers = [], activeProvider = 'deepseek', draftProvider = 'deepseek', draftProfiles = new Map();
  let mode = 'role', sessionId = '', appliedRole = '', busy = false, probing = false, files = [];
  let toastTimer, taskTimer, startedAt, taskStage = '', undoState, pendingSetup = null;
  let refreshPromise, resultCount = 0, runOutcome = 'idle', currentTask = '', taskController = null, cancelTimer, pendingSession = '';
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fileName = path => path.slice(path.indexOf('/') + 1).replace(/^[a-f0-9]{8}-/, '');
  function storageGet(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } }
  function toast(text, action, callback) {
    const el = $('toast'); el.replaceChildren(document.createTextNode(text));
    if (action) { const button = document.createElement('button'); button.textContent = action; button.onclick = () => { callback(); el.classList.remove('show'); }; el.append(button); }
    el.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), action ? 9000 : 4200);
  }
  async function api(path, body) {
    let response;
    try { response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Office-Token': token}, body: JSON.stringify(body)}); }
    catch { throw new Error('无法连接本地服务，请确认启动窗口仍在运行，然后重试。'); }
    let value; try { value = await response.json(); } catch { throw new Error('服务返回异常，请刷新页面后重试。'); }
    if (!response.ok) throw new Error(value.error || '请求未完成。');
    return value;
  }
  function snapshot() { return {session: sessionId, draft: $('text').value, messages: [...$('messages').childNodes], traces: [...$('traces').childNodes], scroll: $('scroll').scrollTop, status: $('status').textContent}; }
  function restore(state) {
    sessionId = state.session; $('text').value = state.draft;
    $('messages').replaceChildren(...state.messages); $('traces').replaceChildren(...state.traces);
    $('welcome').hidden = !!state.messages.length; $('scroll').scrollTop = state.scroll; $('latestMessage').hidden = true;
    setStatus(state.status || '就绪');
  }
  function setMode(next) {
    if (busy || next === mode) return;
    states[mode] = snapshot(); mode = next; restore(states[mode]);
    document.querySelectorAll('.mode').forEach(el => { const active = el.dataset.mode === mode; el.classList.toggle('active', active); el.setAttribute('aria-selected', String(active)); el.tabIndex = active ? 0 : -1; });
    $('modeTitle').textContent = mode === 'role' ? '办公顾问' : '办公执行助理';
    $('modeNote').textContent = mode === 'role' ? 'Shift + Enter 换行' : '原始文件会保留';
    $('intro').textContent = mode === 'role' ? '聊聊你的想法，或者给我一个具体任务。' : '先选择资料，再说明你需要什么结果。';
    $('composerHint').textContent = mode === 'role' ? '角色助手适合讨论与写作；处理文件请使用执行 Agent。' : '已选资料会随任务指定给 Agent；新文件保存在生成结果中。';
    updateSetup();
  }
  function newChat() {
    if (busy) return;
    const old = snapshot(), oldMode = mode, oldFiles = [...selectedFiles];
    undoState = old; restore(emptyState()); states[mode] = emptyState(); selectedFiles.clear(); renderFiles(); renderAttachments();
    toast('已新建会话，工作文件仍然保留。', '撤销', () => { if (mode === oldMode && undoState === old && !busy && !$('messages').children.length && !$('text').value) { restore(old); selectedFiles.clear(); oldFiles.forEach(p => selectedFiles.add(p)); renderFiles(); renderAttachments(); } });
  }
  function setStatus(text) { $('status').textContent = text; }
  function setBusy(value) {
    busy = value;
    for (const id of ['send', 'demo', 'demoInline', 'newChat', 'uploadButton', 'upload', 'rolePrompt']) $(id).disabled = value;
    for (const id of ['provider', 'key', 'baseUrl', 'model', 'loadModels', 'testConnection', 'saveSettings', 'clearPreferences', 'streamOutput', 'maxOutput', 'contextWindow']) $(id).disabled = value || probing;
    $('thinking').disabled = value || probing || !['deepseek', 'qwen'].includes(draftProvider);
    document.querySelectorAll('.mode, .file-select, .attachment-remove').forEach(el => el.disabled = value);
    const picker = $('modelPicker'); if (picker) picker.disabled = value || probing;
    $('send').textContent = value ? '…' : '↗'; $('send').setAttribute('aria-label', value ? '任务进行中' : '发送任务');
    $('workbench').setAttribute('aria-busy', String(value));
  }
  function setFocus(value) {
    document.body.classList.toggle('focus-mode', value);
    $('focusMode').setAttribute('aria-pressed', String(value));
    $('focusMode').setAttribute('aria-label', value ? '退出专注模式' : '进入专注模式');
    $('focusMode').title = value ? '退出专注模式（Esc）' : '专注模式';
    const navCTA = document.querySelector('.nav-cta'), arrow = document.createElement('i');
    arrow.textContent = '↗'; navCTA.href = value ? '#home' : '#studio'; navCTA.replaceChildren(document.createTextNode(value ? '浏览首页 ' : '进入工作台 '), arrow);
    window.dispatchEvent(new CustomEvent('antou:focus', {detail: value}));
    if (value) { window.scrollTo({top: 0, behavior: 'instant'}); $('text').focus({preventScroll: true}); }
    else requestAnimationFrame(() => $('workbench').scrollIntoView({block: 'start', behavior: 'instant'}));
  }
  function goStudio(focus = false) { if (focus) setFocus(true); else $('workbench').scrollIntoView({behavior: reduced() ? 'instant' : 'smooth', block: 'start'}); }
  $('focusMode').onclick = () => setFocus(!document.body.classList.contains('focus-mode'));
  $('quickDesk').onclick = () => goStudio(true);
  $('newChat').onclick = newChat;
  document.querySelectorAll('.mode').forEach(el => {
    el.tabIndex = el.dataset.mode === mode ? 0 : -1;
    el.onclick = () => setMode(el.dataset.mode);
    el.onkeydown = event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); if (!busy) { setMode(mode === 'role' ? 'agent' : 'role'); document.querySelector('.mode.active').focus(); } } };
  });
  $('filesToggle').onclick = () => { $('workbench').classList.add('show-files'); $('closeFiles').focus({preventScroll: true}); };
  $('closeFiles').onclick = () => { $('workbench').classList.remove('show-files'); $('filesToggle').focus({preventScroll: true}); };
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); if (!$('settings').open) goStudio(true); }
    if ((event.ctrlKey || event.metaKey) && event.key === ',') { event.preventDefault(); openSettings(); }
    if (event.key === 'Escape' && !$('settings').open) { if ($('workbench').classList.contains('show-files')) $('closeFiles').click(); else if (document.body.classList.contains('focus-mode')) setFocus(false); }
  });
  let heroVisible = true, benchVisible = false;
  function updateDock() { $('quickDesk').hidden = heroVisible || benchVisible || document.body.classList.contains('focus-mode'); }
  const observer = new IntersectionObserver(entries => { for (const entry of entries) { if (entry.target.id === 'home') heroVisible = entry.isIntersecting; else benchVisible = entry.isIntersecting; } updateDock(); }, {threshold: .03});
  observer.observe($('home')); observer.observe($('workbench'));
  window.addEventListener('antou:focus', updateDock);
  document.querySelectorAll('.nav a, .footer a').forEach(link => link.addEventListener('click', event => {
    if (document.body.classList.contains('focus-mode')) { event.preventDefault(); const target = link.getAttribute('href'); setFocus(false); requestAnimationFrame(() => document.querySelector(target)?.scrollIntoView({behavior: reduced() ? 'instant' : 'smooth'})); }
  }));

  // A small DOM-only formatter: no model-supplied HTML is ever inserted.
  function inline(parent, text) {
    const regex = /(\*\*([^*]+)\*\*|`([^`]+)`)/g; let at = 0, match;
    while ((match = regex.exec(text))) { parent.append(document.createTextNode(text.slice(at, match.index))); const el = document.createElement(match[2] ? 'strong' : 'code'); el.textContent = match[2] || match[3]; parent.append(el); at = regex.lastIndex; }
    parent.append(document.createTextNode(text.slice(at)));
  }
  function formatAnswer(container, text) {
    let code = null, list = null;
    for (const line of text.split('\n')) {
      if (line.trim().startsWith('```')) { list = null; if (code) code = null; else { const pre = document.createElement('pre'); code = document.createElement('code'); pre.append(code); container.append(pre); } continue; }
      if (code) { code.append(document.createTextNode(line + '\n')); continue; }
      if (!line.trim()) { list = null; continue; }
      const bullet = line.match(/^\s*(?:[-*]|\d+[.)、])\s+(.+)$/), heading = line.match(/^#{1,4}\s+(.+)$/);
      if (bullet) { if (!list) { list = document.createElement('ul'); container.append(list); } const li = document.createElement('li'); inline(li, bullet[1]); list.append(li); }
      else { list = null; const el = document.createElement(heading ? 'h4' : 'p'); inline(el, heading ? heading[1] : line); container.append(el); }
    }
  }
  function addMessage(who, text, retryTask) {
    const scroll = $('scroll'), nearEnd = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 90;
    $('welcome').hidden = true;
    const article = document.createElement('article'); article.className = 'message ' + who;
    const label = document.createElement('div'); label.className = 'who'; label.textContent = {user: 'YOU / 你', assistant: mode === 'agent' ? 'ANTOU / 执行 Agent' : 'ANTOU / 办公顾问', error: '未完成 · 可以继续处理', notice: '提示 / NOTICE'}[who];
    const content = document.createElement('div'); content.className = 'text';
    if (who === 'assistant') formatAnswer(content, text); else content.textContent = text;
    article.append(label, content);
    if (who === 'assistant') {
      const links = [...new Set(text.match(/outputs\/[^\n\r，；]+?\.(?:xlsx|docx|csv|txt|md)/g) || [])];
      for (const path of links) { const a = document.createElement('a'); a.href = '/download?path=' + encodeURIComponent(path); a.className = 'file-inline'; a.textContent = '↙ ' + fileName(path); article.append(a); }
      const copy = document.createElement('button'); copy.className = 'message-copy'; copy.textContent = '复制内容'; copy.onclick = async () => { try { await navigator.clipboard.writeText(article.dataset.rawAnswer || text); copy.textContent = '已复制 ✓'; setTimeout(() => copy.textContent = '复制内容', 1800); } catch { toast('复制未成功，请选中文字后复制。'); } }; article.append(copy);
    }
    if (who === 'error') {
      const actions = document.createElement('div'); actions.className = 'error-actions';
      if (retryTask) { const retry = document.createElement('button'); retry.textContent = '重试这项任务 ↗'; retry.onclick = () => { if (!busy) { if (retryTask.mode !== mode) setMode(retryTask.mode); submitTask(retryTask.text, retryTask.attachments, false); } }; actions.append(retry); }
      const settings = document.createElement('button'); settings.textContent = '检查模型设置'; settings.onclick = () => openSettings(); actions.append(settings); article.append(actions);
    }
    $('messages').append(article);
    if (nearEnd || who === 'user') scroll.scrollTop = scroll.scrollHeight; else $('latestMessage').hidden = false;
    return article;
  }
  $('latestMessage').onclick = () => { $('scroll').scrollTop = $('scroll').scrollHeight; $('latestMessage').hidden = true; };
  $('scroll').onscroll = () => { if ($('scroll').scrollHeight - $('scroll').scrollTop - $('scroll').clientHeight < 90) $('latestMessage').hidden = true; };

  function validUrl(value) { try { const u = new URL(value); return !u.username && !u.password && !u.search && !u.hash && (u.protocol === 'https:' || (u.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(u.hostname))); } catch { return false; } }
  function persistPreferences() {
    const entries = {};
    for (const [id, profile] of profiles) { if (validUrl(profile.base_url)) entries[id] = {base_url: profile.base_url, model: profile.model.slice(0, 200), thinking: !!profile.thinking, max_output_tokens: profile.max_output_tokens || 6000, context_window: profile.context_window || 32000, stream_output: profile.stream_output !== false}; }
    try { localStorage.setItem('antou.preferences.v3', JSON.stringify({activeProvider, profiles: entries})); } catch { toast('设置已应用，本次浏览器无法记住偏好。'); }
  }
  const ready = api('/api/providers').then(items => {
    providers = items; const prefs = storageGet('antou.preferences.v3'); $('provider').replaceChildren();
    for (const item of items) {
      const saved = prefs?.profiles?.[item.id];
      profiles.set(item.id, {provider: item.id, base_url: saved && typeof saved.base_url === 'string' && validUrl(saved.base_url) ? saved.base_url : item.base_url, model: saved && typeof saved.model === 'string' ? saved.model.slice(0, 200) : item.default_model, api_key: '', thinking: !!saved?.thinking, max_output_tokens: saved?.max_output_tokens || 6000, context_window: saved?.context_window || 32000, stream_output: saved?.stream_output !== false});
      const option = document.createElement('option'); option.value = item.id; option.textContent = item.name; $('provider').append(option);
    }
    if (profiles.has(prefs?.activeProvider)) activeProvider = prefs.activeProvider;
    draftProfiles = cloneProfiles(); showDraft(activeProvider); updateBadge(); updateSetup();
  }).catch(error => { toast(error.message, '刷新页面', () => location.reload()); throw error; }); ready.catch(() => {});
  function cloneProfiles() { return new Map([...profiles].map(([id, profile]) => [id, {...profile}])); }
  function saveDraft() { if (draftProfiles.has(draftProvider)) draftProfiles.set(draftProvider, {provider: draftProvider, base_url: $('baseUrl').value.trim(), model: $('model').value.trim(), api_key: $('key').value.trim(), thinking: !$('thinking').disabled && $('thinking').checked, max_output_tokens: Number($('maxOutput').value), context_window: Number($('contextWindow').value), stream_output: $('streamOutput').checked}); }
  function showDraft(id) {
    const item = providers.find(p => p.id === id); if (!item) return;
    draftProvider = id; const profile = draftProfiles.get(id); $('provider').value = id;
    $('baseUrl').value = profile.base_url; $('model').value = profile.model; $('key').value = profile.api_key; $('key').type = 'password'; $('toggleKey').textContent = '显示'; $('toggleKey').setAttribute('aria-pressed', 'false');
    keyHint(item, profile.base_url);
    $('streamOutput').checked = profile.stream_output !== false;
    $('thinking').checked = !!profile.thinking; $('thinking').disabled = !['deepseek', 'qwen'].includes(id);
    $('maxOutput').value = profile.max_output_tokens || 6000; $('contextWindow').value = profile.context_window || 32000;
    $('connectionStatus').className = 'field-note'; $('connectionStatus').textContent = '先填写密钥，再读取模型列表；执行 Agent 需要支持工具调用的模型。';
    for (const name of ['baseUrl', 'model', 'key']) $(name).removeAttribute('aria-invalid');
    $('models').replaceChildren(); $('modelPicker')?.remove();
  }
  // An environment key is only sent to the preset's official host (same scheme, host and port).
  function sameOrigin(a, b) { try { return !!a && !!b && new URL(a).origin === new URL(b).origin; } catch { return false; } }
  function envKeyUsable(item, profile) { return !!item && !!profile && item.has_key && item.id !== 'custom' && sameOrigin(profile.base_url, item.base_url); }
  function keyHint(item, baseUrl) {
    const profile = {base_url: baseUrl};
    $('key').placeholder = envKeyUsable(item, profile) ? '环境变量已配置，可留空' : item.requires_key ? '填写该服务商的 API Key' : '本地服务通常可留空';
    $('keyHint').textContent = envKeyUsable(item, profile) ? '已检测到该服务商环境变量，仅发送到官方地址。' : item.has_key && item.id !== 'custom' ? '接口地址已修改：环境变量中的 Key 不会发送到这个地址，请填写对应的 Key。' : '密钥仅保留在本次页面内存；刷新后需要重新填写。';
  }
  function configured() { const item = providers.find(p => p.id === activeProvider), profile = profiles.get(activeProvider); return !!item && !!profile && !!profile.model && validUrl(profile.base_url) && (!item.requires_key || !!profile.api_key || envKeyUsable(item, profile)); }
  function updateBadge() { const item = providers.find(p => p.id === activeProvider), profile = profiles.get(activeProvider); if (item && profile) { $('activeModel').textContent = item.name + ' / ' + (profile.model || '选择模型') + (configured() ? '' : ' · 待设置'); $('activeModel').parentElement.classList.toggle('needs-setup', !configured()); } }
  function updateSetup() {
    const connected = configured(); $('setupModel').classList.toggle('complete', connected); $('setupModel').querySelector('small').textContent = connected ? '已填写' : '待设置';
    $('setupFiles').classList.toggle('complete', !!selectedFiles.size); $('setupFiles').querySelector('small').textContent = selectedFiles.size ? '已选 ' + selectedFiles.size + ' 份' : '按需添加';
    $('setupTask').querySelector('small').textContent = mode === 'role' ? '写作与讨论' : '执行与交付';
  }
  async function openSettings(id) {
    if (probing || busy) { toast('当前任务进行中，完成后可修改模型。'); return; }
    try { await ready; draftProfiles = cloneProfiles(); showDraft(id || activeProvider); $('rolePrompt').value = appliedRole; $('settings').showModal(); document.body.classList.add('dialog-open'); }
    catch (error) { toast(error.message); }
  }
  document.querySelectorAll('[data-open-settings]').forEach(el => el.onclick = () => openSettings());
  document.querySelectorAll('[data-provider]').forEach(el => el.onclick = () => openSettings(el.dataset.provider));
  $('setupModel').onclick = () => openSettings(); $('setupFiles').onclick = () => !busy && $('upload').click(); $('setupTask').onclick = () => $('text').focus({preventScroll: true});
  $('provider').onchange = () => { const id = $('provider').value; saveDraft(); showDraft(id); };
  $('baseUrl').oninput = () => { const item = providers.find(p => p.id === draftProvider); if (item) keyHint(item, $('baseUrl').value.trim()); };
  $('closeSettings').onclick = () => $('settings').close();
  $('settings').addEventListener('close', () => { document.body.classList.remove('dialog-open'); pendingSetup = null; });
  $('settings').addEventListener('click', e => { const r = $('settings').getBoundingClientRect(); if (e.target === $('settings') && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) $('settings').close(); });
  $('toggleKey').onclick = () => { const show = $('key').type === 'password'; $('key').type = show ? 'text' : 'password'; $('toggleKey').textContent = show ? '隐藏' : '显示'; $('toggleKey').setAttribute('aria-pressed', String(show)); $('toggleKey').setAttribute('aria-label', show ? '隐藏密钥' : '显示密钥'); };
  $('clearPreferences').onclick = () => { try { localStorage.removeItem('antou.preferences.v3'); toast('已清除记住的配置，当前会话仍可继续使用。'); } catch { toast('浏览器未允许清除配置。'); } };
  $('saveSettings').onclick = () => {
    saveDraft(); const profile = draftProfiles.get(draftProvider), preset = providers.find(p => p.id === draftProvider);
    let problem = !validUrl(profile.base_url) ? '请输入正确的 API 地址：远程 HTTPS，或本机 HTTP。' : !profile.model ? '请选择或填写模型名称。' : preset.requires_key && !profile.api_key && !envKeyUsable(preset, profile) ? '请填写 ' + preset.name + ' API Key' + (preset.has_key ? '（接口地址已修改，环境变量中的 Key 只用于官方地址）' : '') + '。' : '';
    if (problem) { $('connectionStatus').className = 'field-note error'; $('connectionStatus').textContent = problem; const field = !validUrl(profile.base_url) ? $('baseUrl') : !profile.model ? $('model') : $('key'); field.setAttribute('aria-invalid', 'true'); field.focus(); return; }
    if (!Number.isInteger(profile.max_output_tokens) || profile.max_output_tokens < 256 || profile.max_output_tokens > 16000 || !Number.isInteger(profile.context_window) || profile.context_window < 4096 || profile.context_window > 1000000 || profile.max_output_tokens + 512 >= profile.context_window) { $('connectionStatus').className = 'field-note error'; $('connectionStatus').textContent = '请填写有效的输出与上下文预算；上下文需大于输出加 512。'; return; }
    const previous = profiles.get(activeProvider);
    const changed = activeProvider !== draftProvider || previous.base_url !== profile.base_url || previous.model !== profile.model || previous.api_key !== profile.api_key || previous.thinking !== profile.thinking || previous.max_output_tokens !== profile.max_output_tokens || previous.context_window !== profile.context_window || appliedRole !== $('rolePrompt').value;
    profiles.clear(); for (const [id, value] of draftProfiles) profiles.set(id, {...value});
    activeProvider = draftProvider; appliedRole = $('rolePrompt').value; persistPreferences(); updateBadge(); updateSetup();
    if (changed) { sessionId = ''; states.role.session = ''; states.agent.session = ''; }
    const pending = pendingSetup; $('settings').close();
    if (pending) { $('text').value = pending.text; toast('模型已配置，任务草稿已保留。点击发送即可开始。'); $('text').focus({preventScroll: true}); }
    else toast(changed && $('messages').children.length ? '设置已更新，后续任务使用新上下文；旧对话仍保留供参考。' : '模型设置已应用。');
  };
  async function probe(path) {
    if (busy || probing) return; saveDraft(); const profile = {...draftProfiles.get(draftProvider)};
    probing = true; setBusy(busy); $('connectionStatus').className = 'field-note'; $('connectionStatus').textContent = path === '/api/models' ? '正在读取模型列表…' : '正在测试对话连接…';
    try {
      const value = await api(path, profile);
      if (value.models) {
        $('models').replaceChildren(); $('modelPicker')?.remove();
        const picker = document.createElement('select'); picker.id = 'modelPicker'; picker.setAttribute('aria-label', '选择可用模型'); picker.style.marginTop = '8px';
        const first = document.createElement('option'); first.value = ''; first.textContent = '选择可用模型（' + value.count + '）'; picker.append(first);
        for (const name of value.models) { const item = document.createElement('option'); item.value = item.textContent = name; $('models').append(item.cloneNode(true)); picker.append(item); }
        picker.onchange = () => { if (picker.value) $('model').value = picker.value; }; $('model').closest('.model-input').after(picker);
      }
      $('connectionStatus').className = 'field-note success'; $('connectionStatus').textContent = value.message;
    } catch (error) { $('connectionStatus').className = 'field-note error'; $('connectionStatus').textContent = error.message; }
    finally { probing = false; setBusy(busy); }
  }
  $('loadModels').onclick = () => probe('/api/models'); $('testConnection').onclick = () => probe('/api/test');

  function renderAttachments() {
    $('attachments').replaceChildren();
    for (const path of selectedFiles) { const chip = document.createElement('span'); chip.className = 'attachment-chip'; chip.append(document.createTextNode(fileName(path))); const remove = document.createElement('button'); remove.className = 'attachment-remove'; remove.textContent = '×'; remove.disabled = busy; remove.setAttribute('aria-label', '取消选择 ' + fileName(path)); remove.onclick = () => { selectedFiles.delete(path); renderAttachments(); renderFiles(); }; chip.append(remove); $('attachments').append(chip); }
    updateSetup();
  }
  function renderFiles() {
    const query = $('fileSearch').value.trim().toLowerCase();
    for (const folder of ['inputs', 'outputs']) {
      const target = $(folder); target.replaceChildren(); const all = files.filter(x => x.path.startsWith(folder + '/')), items = all.filter(x => fileName(x.path).toLowerCase().includes(query));
      $(folder === 'inputs' ? 'inputCount' : 'outputCount').textContent = all.length;
      if (!items.length) { const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = query ? '没有匹配的文件。' : folder === 'inputs' ? '上传资料后，可勾选用于本次任务。' : '完成的文件会出现在这里。'; target.append(empty); }
      for (const item of items) {
        const row = document.createElement('div'); row.className = 'file';
        if (folder === 'inputs') { const select = document.createElement('input'); select.type = 'checkbox'; select.className = 'file-select'; select.checked = selectedFiles.has(item.path); select.disabled = busy; select.setAttribute('aria-label', '使用 ' + fileName(item.path)); select.onchange = () => { if (select.checked && selectedFiles.size >= 10) { select.checked = false; toast('每次最多选择 10 份资料。'); return; } if (select.checked) selectedFiles.add(item.path); else selectedFiles.delete(item.path); renderAttachments(); }; row.append(select); }
        const a = document.createElement('a'); a.href = '/download?path=' + encodeURIComponent(item.path); a.download = ''; a.className = 'file-download'; a.title = '下载 ' + fileName(item.path);
        const name = document.createElement('span'); name.className = 'file-name'; name.append(document.createTextNode(fileName(item.path)));
        const size = document.createElement('small'); size.textContent = (item.bytes / 1024).toFixed(1) + ' KB' + (item.modified_at ? ' · ' + new Date(item.modified_at * 1000).toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : ''); name.append(size);
        const arrow = document.createElement('span'); arrow.className = 'file-arrow'; arrow.textContent = '↙'; a.append(name, arrow); row.append(a); target.append(row);
      }
    }
  }
  async function refreshFiles() {
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => { try { files = await api('/api/files'); renderFiles(); } catch (error) { toast(error.message); } finally { refreshPromise = null; } })();
    return refreshPromise;
  }
  $('fileSearch').oninput = renderFiles; $('refresh').onclick = refreshFiles; $('uploadButton').onclick = () => $('upload').click();
  async function uploadFiles(list) {
    if (busy || !list.length) return;
    const valid = [], issues = []; for (const file of list) { if (!/\.(csv|xlsx|docx|txt|md)$/i.test(file.name)) issues.push(file.name + '：格式不支持'); else if (file.size > 20 * 1024 * 1024) issues.push(file.name + '：超过 20MB'); else valid.push(file); }
    setBusy(true); let uploaded = 0;
    try {
      for (const [index, file] of valid.entries()) {
        setStatus('上传 ' + (index + 1) + '/' + valid.length);
        try {
          const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = () => reject(new Error('读取失败')); reader.readAsDataURL(file); });
          const result = await api('/api/upload', {name: file.name, data}); uploaded++; if (selectedFiles.size < 10) selectedFiles.add(result.file);
        } catch (error) { issues.push(file.name + '：' + error.message); }
      }
    } finally { setBusy(false); setStatus(issues.length ? '部分文件未上传' : '资料已就绪'); $('upload').value = ''; await refreshFiles(); renderAttachments(); }
    if (uploaded) toast('已上传 ' + uploaded + ' 份资料，并选用于本次任务。', mode === 'role' ? '用 Agent 处理' : undefined, () => { const draft = $('text').value; setMode('agent'); if (!$('text').value) $('text').value = draft; $('text').focus({preventScroll: true}); });
    if (issues.length) addMessage('error', '以下文件未上传，其余文件已保留：\n' + issues.join('\n'));
  }
  $('upload').onchange = () => uploadFiles([...$('upload').files]);
  $('workbench').addEventListener('dragover', e => { if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); $('dropZone').classList.add('dragging'); } });
  $('workbench').addEventListener('dragleave', e => { if (!$('workbench').contains(e.relatedTarget)) $('dropZone').classList.remove('dragging'); });
  $('workbench').addEventListener('drop', e => { e.preventDefault(); $('dropZone').classList.remove('dragging'); uploadFiles([...e.dataTransfer.files]); });

  function updateElapsed() { $('taskElapsed').textContent = Math.floor((Date.now() - startedAt) / 1000) + ' 秒'; $('taskStage').textContent = taskStage; }
  function paintStream(reply) {
    const scroll = $('scroll'), atEnd = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 90;
    reply.content.textContent = reply.text; reply.article.dataset.rawAnswer = reply.text;
    if (atEnd) scroll.scrollTop = scroll.scrollHeight; else $('latestMessage').hidden = false;
  }
  function streamDelta(event) {
    let reply = streamedReplies.get(event.reply_id);
    if (!reply) { const article = addMessage('assistant', ''); article.classList.add('streaming'); reply = {article, content: article.querySelector('.text'), text: '', frame: null, ended: false}; streamedReplies.set(event.reply_id, reply); }
    reply.text += event.text;
    if (!reply.frame) reply.frame = requestAnimationFrame(() => { reply.frame = null; paintStream(reply); });
    taskStage = '正在生成正文…'; updateElapsed();
  }
  function finishReply(event) {
    const reply = streamedReplies.get(event.reply_id);
    if (reply) { if (reply.frame) cancelAnimationFrame(reply.frame); const article = addMessage('assistant', event.text); reply.article.replaceWith(article); streamedReplies.delete(event.reply_id); }
    else addMessage('assistant', event.text);
  }
  function streamEvent(event, task) {
    if (event.type === 'status') { taskStage = event.text; setStatus(event.text); updateElapsed(); }
    if (event.type === 'task') currentTask = event.task_id;
    // The server stores a session only after a complete run, so adopt the id only on "done".
    if (event.type === 'session') { pendingSession = event.session_id; if (event.reset) addMessage('notice', event.text || '本次任务在新会话中进行。'); }
    if (event.type === 'session_expired') {
      // Start fresh explicitly: forget the dead session id, put the task back, never resend automatically.
      runOutcome = 'expired'; sessionId = ''; states.role.session = ''; states.agent.session = '';
      if (task && !$('text').value.trim()) $('text').value = task.text;
      addMessage('notice', event.text);
    }
    if (event.type === 'cancelled') { runOutcome = 'cancelled'; addMessage('notice', event.text); }
    if (event.type === 'answer_delta') streamDelta(event);
    if (event.type === 'reply_end') { const reply = streamedReplies.get(event.reply_id); if (reply) { if (reply.frame) cancelAnimationFrame(reply.frame); paintStream(reply); reply.content.replaceChildren(); formatAnswer(reply.content, reply.text); reply.article.classList.remove('streaming'); reply.article.querySelector('.who').textContent = 'ANTOU / 步骤说明'; reply.ended = true; } }
    if (event.type === 'context_budget' && event.dropped_turns) addMessage('notice', '为保持上下文预算，本次省略最早的 ' + event.dropped_turns + ' 轮对话。当前任务和工具链完整保留；完整正文仍可在本机历史中查看。');
    if (event.type === 'answer') { runOutcome = 'answered'; finishReply(event); }
    if (event.type === 'error') { runOutcome = 'error'; addMessage('error', event.text, task); }
    if (event.type === 'done') { runOutcome = runOutcome === 'error' ? 'error' : 'done'; if (pendingSession && runOutcome === 'done') sessionId = pendingSession; }
    if (event.type === 'tool_start') {
      const box = document.createElement('details'); box.className = 'trace'; const title = document.createElement('summary'); title.textContent = '◌ ' + (toolNames[event.name] || event.name) + ' / 进行中';
      box.append(title, document.createElement('pre')); $('traces').append(box); traceMap.set(event.id, box); taskStage = toolNames[event.name] || event.name; setStatus(taskStage); updateElapsed();
    }
    if (event.type === 'tool_end') {
      const box = traceMap.get(event.id); if (!box) return; const failed = !!event.result?.error;
      box.classList.add(failed ? 'fail' : 'ok'); box.firstChild.textContent = (failed ? '! ' : '✓ ') + (toolNames[event.name] || event.name);
      box.lastChild.textContent = JSON.stringify(event.result, null, 2); if (event.result?.file) resultCount++; refreshFiles();
    }
  }
  function cancelTask() {
    if (!busy || !taskController || runOutcome !== 'running') return;
    $('cancelTask').disabled = true; $('cancelTask').textContent = '正在停止…'; setStatus('正在停止…');
    if (currentTask) api('/api/cancel', {task_id: currentTask}).catch(() => {});
    else taskController.abort();
    // If the server never answers, closing the stream also cancels on the server side.
    cancelTimer = setTimeout(() => taskController && taskController.abort(), 4000);
  }
  $('cancelTask').onclick = cancelTask;
  async function run(path, body, task) {
    streamedReplies.clear();
    setBusy(true); currentTask = ''; pendingSession = ''; taskController = new AbortController();
    $('cancelTask').hidden = false; $('cancelTask').disabled = false; $('cancelTask').textContent = '停止任务 ■'; undoState = null; traceMap.clear(); $('traces').replaceChildren(); resultCount = 0; runOutcome = 'running';
    startedAt = Date.now(); taskStage = path === '/api/demo' ? '正在运行本地演示' : '正在等待模型响应'; $('taskProgress').hidden = false; updateElapsed(); taskTimer = setInterval(updateElapsed, 1000);
    let receivedAnswer = false;
    try {
      const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Office-Token': token}, body: JSON.stringify(body), signal: taskController.signal});
      if (!response.ok) throw new Error((await response.json()).error || '请求失败。');
      const reader = response.body.getReader(), decoder = new TextDecoder(); let pending = '';
      while (true) {
        const {value, done} = await reader.read(); pending += decoder.decode(value || new Uint8Array(), {stream: !done}); let split;
        while ((split = pending.indexOf('\n')) >= 0) { const line = pending.slice(0, split); pending = pending.slice(split + 1); if (line) { const event = JSON.parse(line); if (event.type === 'answer' || event.type === 'answer_delta') receivedAnswer = true; streamEvent(event, task); } }
        if (done) { if (pending.trim()) streamEvent(JSON.parse(pending), task); break; }
      }
      if (runOutcome === 'running') throw new Error('连接提前结束，任务未收到完整结果。');
    } catch (error) {
      if (error && error.name === 'AbortError') { if (runOutcome !== 'cancelled') { runOutcome = 'cancelled'; addMessage('notice', '任务已停止。已经生成的文件保留在文件列表中。'); } }
      else { runOutcome = 'error'; addMessage('error', receivedAnswer ? '连接中断，但已收到部分结果。请先检查现有文件，确认后再重试。' : (error instanceof TypeError ? '连接已中断，请确认本地服务仍在运行，再重试。' : error.message), task); }
    } finally {
      for (const reply of streamedReplies.values()) { if (reply.frame) cancelAnimationFrame(reply.frame); paintStream(reply); if (!reply.ended) { reply.article.classList.remove('streaming'); reply.article.classList.add('partial-answer'); reply.article.querySelector('.who').textContent = 'ANTOU / 未完成的部分回答'; } }
      clearTimeout(cancelTimer); taskController = null; currentTask = ''; $('cancelTask').hidden = true;
      clearInterval(taskTimer); $('taskProgress').hidden = true; setBusy(false); await refreshFiles();
      const seconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
      setStatus({error: '未完成 · 可重试', cancelled: '已停止 · 文件已保留', expired: '上下文已失效 · 请确认后重新发送'}[runOutcome] || '已完成 · ' + seconds + ' 秒');
      if (runOutcome === 'expired') $('text').focus({preventScroll: true});
      if (!['error', 'cancelled', 'expired'].includes(runOutcome) && resultCount) toast('任务完成，生成了 ' + resultCount + ' 份文件。', '查看结果', () => { if (matchMedia('(max-width:760px)').matches) $('filesToggle').click(); $('outputs').scrollIntoView({block: 'nearest', behavior: reduced() ? 'instant' : 'smooth'}); });
    }
  }
  async function submitTask(text, attachments = [...selectedFiles], echo = true) {
    if (busy || !text.trim()) return;
    try { await ready; } catch { return; }
    if (busy) return;
    const item = {text: text.trim(), attachments, mode};
    if (mode === 'role' && attachments.length) { const draft = $('text').value || text; setMode('agent'); if (!$('text').value) $('text').value = draft; toast('已切换到执行 Agent，草稿和资料已保留；点击发送即可处理文件。'); return; }
    if (!configured()) { await openSettings(); pendingSetup = item; $('connectionStatus').className = 'field-note error'; $('connectionStatus').textContent = '开始前请先配置模型。你的任务草稿已保留，应用后可继续发送。'; return; }
    if (echo) addMessage('user', text); $('text').value = '';
    run('/api/chat', {...profiles.get(activeProvider), stream: profiles.get(activeProvider).stream_output !== false, text, mode, session_id: sessionId, role_prompt: appliedRole, attachments}, item);
  }
  $('form').onsubmit = event => { event.preventDefault(); submitTask($('text').value); };
  $('text').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('form').requestSubmit(); } };
  $('text').oninput = () => { undoState = null; };
  $('demo').onclick = () => { if (busy) return; setMode('agent'); goStudio(); addMessage('user', '运行本地费用汇总演示，生成 Excel 汇总和 Word 说明。'); run('/api/demo', {}, null); };
  $('demoInline').onclick = () => $('demo').click();
  function task(name) {
    if (busy) return;
    const next = name === 'writing' || name === 'meeting' ? 'role' : 'agent'; setMode(next);
    const text = next === 'role' ? '请把下面的会议记录整理为纪要，列出结论、待办、负责人和截止日期。没有明确的信息标记为待确认。\n\n会议记录：' : name === 'routine' ? '请读取我选用的会议记录，生成 Word 纪要，列出结论、待办、负责人和截止日期，缺失信息标记为待确认。' : '请检查我选用的费用表字段，按部门、月份汇总金额，生成 Excel 和 Word 说明，列出异常、处理口径，并核对总额。';
    if (!$('text').value.trim()) $('text').value = text; else toast('已保留你正在编辑的任务。');
    goStudio(); $('text').focus({preventScroll: true});
  }
  document.querySelectorAll('[data-task]').forEach(el => el.onclick = () => task(el.dataset.task));
  document.querySelectorAll('[data-example]').forEach(el => el.onclick = () => task(el.dataset.example));

  // History is loaded explicitly from the local service, never from browser credential storage.
  let historyOffset = 0;
  const statuses = {completed: '已完成', cancelled: '已停止', error: '未完成', interrupted: '已中断', expired: '上下文失效', running: '进行中'};
  const prettyTime = seconds => new Date(seconds * 1000).toLocaleString('zh-CN');
  async function loadHistory(reset = false) {
    if (reset) { historyOffset = 0; $('historyList').replaceChildren(); }
    $('refreshHistory').disabled = $('moreHistory').disabled = true;
    try {
      const value = await api('/api/history?limit=50&offset=' + historyOffset);
      if (reset && !value.items.length) { const p = document.createElement('p'); p.className = 'empty'; p.textContent = '还没有任务。先运行一份演示，记录就会保存在这里。'; $('historyList').append(p); }
      for (const item of value.items) {
        const button = document.createElement('button'); button.className = 'history-item';
        const title = document.createElement('b'); title.textContent = item.title || '未命名任务';
        const meta = document.createElement('small'); meta.textContent = (statuses[item.status] || item.status) + ' · ' + prettyTime(item.started);
        button.append(title, meta); button.onclick = () => showTask(item.id); $('historyList').append(button);
      }
      historyOffset = value.next_offset; $('moreHistory').hidden = value.next_offset === null;
    } catch (error) { toast(error.message); }
    finally { $('refreshHistory').disabled = $('moreHistory').disabled = false; }
  }
  async function showTask(id) {
    try {
      const item = await api('/api/history/' + encodeURIComponent(id)), pane = $('historyDetail'); pane.replaceChildren();
      const title = document.createElement('h3'); title.textContent = item.title || '任务详情'; title.className = 'task-detail-title';
      const meta = document.createElement('p'); meta.className = 'field-note'; meta.textContent = (statuses[item.status] || item.status) + ' · ' + prettyTime(item.started) + (item.model ? ' · ' + item.model : ' · 本地演示');
      const question = document.createElement('p'); question.className = 'history-question'; question.textContent = item.text;
      pane.append(title, meta);
      if (item.text && item.text.length > 600) { const disclosure = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = '查看任务原文（' + item.text.length + ' 字）'; disclosure.className = 'history-question-more'; disclosure.append(summary, question); pane.append(disclosure); } else pane.append(question);
      const output = document.createElement('div'); output.className = 'history-answer';
      if (item.answer) formatAnswer(output, item.answer);
      else if (item.partial_answer) { const warning = document.createElement('p'); warning.className = 'field-note'; warning.textContent = '以下是未完成的部分回答，不是已提交的会话。'; output.append(warning); const partial = document.createElement('p'); partial.textContent = item.partial_answer; output.append(partial); }
      if (item.error) { const error = document.createElement('p'); error.className = 'field-note'; error.textContent = item.error; output.append(error); }
      pane.append(output);
      for (const file of item.files || []) { const a = document.createElement('a'); a.className = 'file-inline'; a.href = '/download?path=' + encodeURIComponent(file); a.textContent = '↙ ' + fileName(file); pane.append(a); }
      const actions = document.createElement('div'); actions.className = 'history-actions';
      const reuse = document.createElement('button'); reuse.className = 'outline-button'; reuse.textContent = '放回输入框'; reuse.onclick = () => { if (busy) return toast('当前任务结束后可操作。'); setMode(item.mode === 'agent' ? 'agent' : 'role'); $('text').value = $('text').value.trim() ? $('text').value + '\n\n' + item.text : item.text; selectedFiles.clear(); (item.attachments || []).slice(0, 10).forEach(p => selectedFiles.add(p)); renderAttachments(); renderFiles(); $('historyDialog').close(); goStudio(true); toast('任务已放回输入框，请确认后发送；不会自动调用模型。'); }; actions.append(reuse);
      if (item.status === 'completed' && item.session_id) { const resume = document.createElement('button'); resume.className = 'solid-button'; resume.textContent = '恢复成功会话 ↗'; resume.onclick = () => resumeSession(item.session_id); actions.append(resume); }
      pane.append(actions);
    } catch (error) { toast(error.message); }
  }
  async function resumeSession(id) {
    if (busy) return toast('当前任务结束后可恢复会话。');
    try {
      await ready; const data = await api('/api/sessions/' + encodeURIComponent(id));
      if (busy) return;
      const settings = data.settings, prior = profiles.get(settings.provider);
      if (!prior) throw new Error('此会话的服务商不受当前版本支持。');
      const restored = {...prior, ...settings, api_key: sameOrigin(prior.base_url, settings.base_url) ? prior.api_key : ''};
      profiles.set(settings.provider, restored); activeProvider = settings.provider; appliedRole = data.role_prompt || '';
      setMode(data.mode); $('messages').replaceChildren(); $('traces').replaceChildren();
      for (const entry of data.transcript || []) addMessage(entry.role === 'user' ? 'user' : 'assistant', entry.content);
      sessionId = data.session_id; states[mode].session = sessionId;
      selectedFiles.clear(); renderAttachments(); renderFiles(); updateBadge(); updateSetup(); persistPreferences();
      $('historyDialog').close(); goStudio(true); setStatus('已恢复成功会话');
      toast(configured() ? '会话已恢复，可以继续提问。' : '会话已恢复；请重新填写模型 Key 后继续。');
    } catch (error) { toast(error.message); }
  }
  $('historyButton').onclick = () => { $('historyDialog').showModal(); document.body.classList.add('dialog-open'); loadHistory(true); };
  $('closeHistory').onclick = () => $('historyDialog').close();
  $('historyDialog').addEventListener('close', () => document.body.classList.remove('dialog-open'));
  $('refreshHistory').onclick = () => loadHistory(true); $('moreHistory').onclick = () => loadHistory(false);
  refreshFiles(); updateSetup();
})();
