(() => {
  const STORAGE_KEY = 'rk3588.console.auth';
  const REFRESH_INTERVAL_MS = 15000;

  const state = {
    token: '',
    role: 'operator',
    userId: 'operator-ui',
    refreshTimer: null,
    plan: null,
    results: [],
  };

  const refs = {};

  function $(id) {
    return document.getElementById(id);
  }

  function initRefs() {
    refs.navTabs = document.querySelectorAll('[data-tab]');
    refs.panels = document.querySelectorAll('[data-tab-panel]');
    refs.userId = $('userId');
    refs.roleSelect = $('roleSelect');
    refs.bootstrapToken = $('bootstrapToken');
    refs.issueTokenBtn = $('issueTokenBtn');
    refs.tokenState = $('tokenState');
    refs.apiBaseLabel = $('apiBaseLabel');
    refs.refreshState = $('refreshState');
    refs.lastRefreshLabel = $('lastRefreshLabel');
    refs.refreshAllBtn = $('refreshAllBtn');
    refs.seedDemoBtn = $('seedDemoBtn');
    refs.snapshotJson = $('snapshotJson');
    refs.metricsGrid = $('metricsGrid');
    refs.devicesTable = $('devicesTable');
    refs.algorithmsTable = $('algorithmsTable');
    refs.librariesTable = $('librariesTable');
    refs.mappingsTable = $('mappingsTable');
    refs.resultsTable = $('resultsTable');
    refs.resultJson = $('resultJson');
    refs.planSummary = $('planSummary');
    refs.planJson = $('planJson');
    refs.toast = $('toast');
    refs.deviceForm = $('deviceForm');
    refs.capabilityForm = $('capabilityForm');
    refs.algorithmForm = $('algorithmForm');
    refs.libraryForm = $('libraryForm');
    refs.mappingForm = $('mappingForm');
    refs.planForm = $('planForm');
    refs.metricFields = Array.from(document.querySelectorAll('[data-metric]'));
  }

  function setTab(tab) {
    refs.navTabs.forEach((node) => {
      node.classList.toggle('active', node.dataset.tab === tab);
    });
    refs.panels.forEach((node) => {
      node.classList.toggle('active', node.dataset.tabPanel === tab);
    });
  }

  function saveAuth() {
    const payload = {
      token: state.token,
      role: state.role,
      userId: state.userId,
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }

  function restoreAuth() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw);
      state.token = String(parsed.token || '');
      state.role = String(parsed.role || 'operator');
      state.userId = String(parsed.userId || 'operator-ui');
    } catch (_error) {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }

  function updateAuthUi() {
    refs.userId.value = state.userId;
    refs.roleSelect.value = state.role;
    if (!state.token) {
      refs.tokenState.textContent = '未登录';
      refs.tokenState.classList.remove('token-chip-live');
      return;
    }
    const shortToken = state.token.slice(0, 16);
    refs.tokenState.textContent = state.role + ' · ' + shortToken + '...';
    refs.tokenState.classList.add('token-chip-live');
  }

  function showToast(message, variant) {
    refs.toast.textContent = message;
    refs.toast.dataset.variant = variant || 'info';
    refs.toast.classList.add('show');
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      refs.toast.classList.remove('show');
    }, 2800);
  }

  function formatNumber(value) {
    if (typeof value !== 'number' || Number.isNaN(value)) {
      return String(value ?? '-');
    }
    return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value);
  }

  function formatTime(value) {
    if (!value) {
      return '-';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    return date.toLocaleString('zh-CN', { hour12: false });
  }

  function pretty(value) {
    return JSON.stringify(value, null, 2);
  }

  function readForm(form) {
    const payload = {};
    const data = new FormData(form);
    data.forEach((value, key) => {
      payload[key] = typeof value === 'string' ? value.trim() : value;
    });
    return payload;
  }

  function capabilitiesFromForm(form) {
    return {
      face: Boolean(form.querySelector('[name="cap_face"]').checked),
      ocr: Boolean(form.querySelector('[name="cap_ocr"]').checked),
    };
  }

  function parseCapabilitiesCsv(raw) {
    return String(raw || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function setMetric(name, value) {
    const node = refs.metricFields.find((item) => item.dataset.metric === name);
    if (!node) {
      return;
    }
    node.textContent = value;
  }

  async function api(path, options) {
    const request = Object.assign({ method: 'GET' }, options || {});
    const headers = new Headers(request.headers || {});
    if (state.token && !headers.has('Authorization')) {
      headers.set('Authorization', 'Bearer ' + state.token);
    }
    if (request.body && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    request.headers = headers;
    const response = await fetch(path, request);
    const isJson = String(response.headers.get('Content-Type') || '').includes('application/json');
    const payload = isJson ? await response.json() : await response.text();
    if (!response.ok) {
      let message = '请求失败';
      if (payload && typeof payload === 'object' && payload.error) {
        message = String(payload.error.message || payload.error.code || message);
      }
      throw new Error(message);
    }
    if (payload && typeof payload === 'object' && payload.success === false) {
      throw new Error(String(payload.error && payload.error.message ? payload.error.message : '请求失败'));
    }
    return payload && typeof payload === 'object' && 'data' in payload ? payload.data : payload;
  }

  function renderMetricGrid(metrics) {
    const preferredKeys = [
      'event_ingested_total',
      'event_duplicate_total',
      'push_dispatch_success_total',
      'push_dispatch_failure_total',
      'gray_batch_plan_cache_hits',
      'gray_batch_plan_cache_misses',
      'gray_batch_plan_cache_last_minute_hit_rate_percent',
      'gray_batch_plan_cache_entries',
    ];
    const numericEntries = Object.entries(metrics || {}).filter((entry) => {
      return typeof entry[1] === 'number';
    });
    const selected = preferredKeys
      .map((key) => [key, metrics[key]])
      .filter((entry) => typeof entry[1] === 'number');
    numericEntries.forEach((entry) => {
      if (selected.length >= 8) {
        return;
      }
      if (!selected.find((item) => item[0] === entry[0])) {
        selected.push(entry);
      }
    });
    refs.metricsGrid.innerHTML = selected
      .slice(0, 8)
      .map(([key, value]) => {
        return '<article class="mini-card"><span>' + key + '</span><strong>' + formatNumber(value) + '</strong></article>';
      })
      .join('');
    if (!refs.metricsGrid.innerHTML) {
      refs.metricsGrid.innerHTML = '<article class="mini-card empty-card"><span>暂无指标</span><strong>-</strong></article>';
    }
  }

  function statusPill(status) {
    const text = String(status || '-');
    const normalized = text.toLowerCase();
    let className = 'status-pill';
    if (['ok', 'active', 'ready', 'online', 'enabled'].includes(normalized)) {
      className += ' status-pill-ok';
    } else if (['inactive', 'offline', 'missing_algorithm', 'missing_base_library', 'degraded'].includes(normalized)) {
      className += ' status-pill-warn';
    } else if (normalized.includes('failed') || normalized.includes('error')) {
      className += ' status-pill-danger';
    }
    return '<span class="' + className + '">' + text + '</span>';
  }

  function renderTableRows(target, rows, emptyText) {
    if (!rows.length) {
      target.innerHTML = '<tr><td class="empty-cell" colspan="12">' + emptyText + '</td></tr>';
      return;
    }
    target.innerHTML = rows.join('');
  }

  function renderDevices(items) {
    const rows = (items || []).map((item) => {
      const capabilities = Object.entries(item.capabilities || {})
        .filter((entry) => Boolean(entry[1]))
        .map((entry) => entry[0])
        .join(', ') || '-';
      return '<tr>' +
        '<td><button class="row-button" data-device-id="' + item.device_id + '">' + item.device_id + '</button></td>' +
        '<td>' + item.protocol + '</td>' +
        '<td>' + (item.stream_url || '-') + '</td>' +
        '<td>' + capabilities + '</td>' +
        '<td>' + statusPill(item.enabled ? 'enabled' : 'disabled') + '</td>' +
        '</tr>';
    });
    renderTableRows(refs.devicesTable, rows, '暂无设备');
  }

  function renderAlgorithms(items) {
    const rows = (items || []).map((item) => {
      return '<tr>' +
        '<td>' + item.algorithm_id + '</td>' +
        '<td>' + item.version + '</td>' +
        '<td>' + statusPill(item.status) + '</td>' +
        '<td>' + (item.capabilities || []).join(', ') + '</td>' +
        '</tr>';
    });
    renderTableRows(refs.algorithmsTable, rows, '暂无算法');
  }

  function renderLibraries(items) {
    const rows = (items || []).map((item) => {
      return '<tr>' +
        '<td>' + item.library_id + '</td>' +
        '<td>' + item.version + '</td>' +
        '<td>' + item.capability + '</td>' +
        '<td>' + statusPill(item.status) + '</td>' +
        '</tr>';
    });
    renderTableRows(refs.librariesTable, rows, '暂无底库');
  }

  function renderMappings(items) {
    const rows = (items || []).map((item) => {
      return '<tr>' +
        '<td>' + item.device_id + '</td>' +
        '<td>' + item.capability + '</td>' +
        '<td>' + item.library_id + '</td>' +
        '<td>' + item.library_version + '</td>' +
        '</tr>';
    });
    renderTableRows(refs.mappingsTable, rows, '暂无映射');
  }

  function renderResults(items) {
    state.results = Array.isArray(items) ? items.slice() : [];
    const rows = state.results.map((item) => {
      return '<tr>' +
        '<td><button class="row-button" data-result-id="' + item.id + '">' + item.device_id + '</button></td>' +
        '<td>' + (item.capability || '-') + '</td>' +
        '<td>' + statusPill(item.status) + '</td>' +
        '<td>' + formatNumber(item.detection_count || 0) + '</td>' +
        '<td>' + formatTime(item.reported_at || item.at) + '</td>' +
        '</tr>';
    });
    renderTableRows(refs.resultsTable, rows, '暂无结果');
  }

  function renderSnapshot(snapshot) {
    refs.snapshotJson.textContent = pretty(snapshot || {});
    setMetric('device_count', formatNumber(snapshot.device_count || 0));
    setMetric('algorithm_count', formatNumber(snapshot.algorithm_count || 0));
    setMetric('base_library_count', formatNumber(snapshot.base_library_count || 0));
    setMetric('push_queue_size', formatNumber(snapshot.push_queue_size || 0));
  }

  function renderPlan(plan) {
    state.plan = plan;
    refs.planJson.textContent = pretty(plan || {});
    const chips = [
      ['预算', plan ? formatNumber(plan.budget || 0) : '-'],
      ['总成本', plan ? formatNumber(plan.total_cost || 0) : '-'],
      ['流数量', plan ? formatNumber(plan.stream_count || 0) : '-'],
      ['就绪流', plan ? formatNumber(plan.ready_stream_count || 0) : '-'],
    ];
    refs.planSummary.innerHTML = chips
      .map((entry) => {
        return '<div class="summary-chip"><div class="chip-label">' + entry[0] + '</div><div class="chip-value">' + entry[1] + '</div></div>';
      })
      .join('');
  }

  function renderResultDetailById(id) {
    const match = state.results.find((item) => String(item.id) === String(id));
    if (!match) {
      return;
    }
    refs.resultJson.textContent = pretty(match);
  }

  async function refreshAll(options) {
    if (!state.token) {
      refs.snapshotJson.textContent = '请先签发 Token';
      refs.metricsGrid.innerHTML = '<article class="mini-card empty-card"><span>未认证</span><strong>-</strong></article>';
      return;
    }
    const silent = Boolean(options && options.silent);
    const tasks = await Promise.allSettled([
      api('/api/v1/runtime/snapshot'),
      api('/api/v1/metrics'),
      api('/api/v1/devices'),
      api('/api/v1/algorithms'),
      api('/api/v1/base-libraries'),
      api('/api/v1/base-libraries/mappings'),
      api('/api/v1/inference/results?limit=10&include_total=true'),
    ]);

    const failed = tasks.find((item) => item.status === 'rejected');
    if (failed) {
      if (!silent) {
        showToast('刷新失败: ' + failed.reason.message, 'danger');
      }
      return;
    }

    const [snapshot, metrics, devices, algorithms, libraries, mappings, results] = tasks.map((item) => item.value);
    renderSnapshot(snapshot);
    renderMetricGrid(metrics);
    renderDevices(devices.items || []);
    renderAlgorithms(algorithms.items || []);
    renderLibraries(libraries.items || []);
    renderMappings(mappings.items || []);
    renderResults(results.items || []);
    refs.lastRefreshLabel.textContent = formatTime(new Date().toISOString());
    if (!silent) {
      showToast('控制台数据已刷新', 'info');
    }
  }

  async function issueToken() {
    state.userId = refs.userId.value.trim() || 'operator-ui';
    state.role = refs.roleSelect.value;
    const headers = {};
    const bootstrapToken = refs.bootstrapToken.value.trim();
    if (bootstrapToken) {
      headers['X-Bootstrap-Token'] = bootstrapToken;
    }
    const data = await api('/api/v1/auth/token', {
      method: 'POST',
      headers,
      body: JSON.stringify({ user_id: state.userId, role: state.role }),
    });
    state.token = String(data.token || '');
    saveAuth();
    updateAuthUi();
    showToast('Token 签发成功', 'success');
    await refreshAll({ silent: true });
  }

  async function submitDeviceForm(event) {
    event.preventDefault();
    const payload = readForm(refs.deviceForm);
    payload.enabled = Boolean(refs.deviceForm.querySelector('[name="enabled"]').checked);
    payload.capabilities = capabilitiesFromForm(refs.deviceForm);
    await api('/api/v1/devices/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showToast('设备已注册', 'success');
    await refreshAll({ silent: true });
  }

  async function submitCapabilityForm(event) {
    event.preventDefault();
    const payload = readForm(refs.capabilityForm);
    payload.capabilities = capabilitiesFromForm(refs.capabilityForm);
    await api('/api/v1/devices/capabilities', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showToast('设备能力已更新', 'success');
    await refreshAll({ silent: true });
  }

  async function submitAlgorithmForm(event) {
    event.preventDefault();
    const payload = readForm(refs.algorithmForm);
    payload.capabilities = parseCapabilitiesCsv(payload.capabilities);
    await api('/api/v1/algorithms/upsert', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showToast('算法已保存', 'success');
    await refreshAll({ silent: true });
  }

  async function submitLibraryForm(event) {
    event.preventDefault();
    const payload = readForm(refs.libraryForm);
    await api('/api/v1/base-libraries/upsert', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showToast('底库已保存', 'success');
    await refreshAll({ silent: true });
  }

  async function submitMappingForm(event) {
    event.preventDefault();
    const payload = readForm(refs.mappingForm);
    payload.execution_hints = {
      model_uri: 'file:///runtime/models/' + payload.library_id + '-' + payload.capability + '.rknn',
    };
    await api('/api/v1/base-libraries/mappings/upsert', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showToast('设备映射已保存', 'success');
    await refreshAll({ silent: true });
  }

  async function submitPlanForm(event) {
    event.preventDefault();
    const payload = readForm(refs.planForm);
    const plan = await api('/api/v1/inference/plan', {
      method: 'POST',
      body: JSON.stringify({ budget: Number(payload.budget || 10) }),
    });
    renderPlan(plan);
    showToast('计划已生成', 'success');
    setTab('planner');
  }

  async function seedDemoData() {
    if (!state.token) {
      throw new Error('请先签发 operator/admin Token');
    }
    const seedDevice = {
      tenant_id: 't1',
      site_id: 's1',
      box_id: 'rk3588-box-1',
      device_id: 'cam-ui-demo',
      protocol: 'rtsp',
      stream_url: 'rtsp://10.0.0.200/live',
      enabled: true,
      capabilities: { face: true, ocr: true },
      execution_hints: {
        stream_uri: 'file:///runtime/streams/cam-ui-demo.h264',
        result_root_uri: 'file:///runtime/results',
        max_samples_per_run: 4,
      },
    };
    const seedAlgorithmFace = {
      algorithm_id: 'face-detector-ui',
      version: '1.0.0',
      capabilities: ['face'],
      status: 'active',
    };
    const seedAlgorithmOcr = {
      algorithm_id: 'ocr-detector-ui',
      version: '1.0.0',
      capabilities: ['ocr'],
      status: 'active',
    };
    const seedLibraryFace = {
      library_id: 'lib-face-ui',
      version: '2026.03',
      capability: 'face',
      status: 'active',
    };
    const seedLibraryOcr = {
      library_id: 'lib-ocr-ui',
      version: '2026.03',
      capability: 'ocr',
      status: 'active',
    };
    const baseMapping = {
      tenant_id: 't1',
      site_id: 's1',
      box_id: 'rk3588-box-1',
      device_id: 'cam-ui-demo',
    };

    await api('/api/v1/devices/register', { method: 'POST', body: JSON.stringify(seedDevice) });
    await api('/api/v1/algorithms/upsert', { method: 'POST', body: JSON.stringify(seedAlgorithmFace) });
    await api('/api/v1/algorithms/upsert', { method: 'POST', body: JSON.stringify(seedAlgorithmOcr) });
    await api('/api/v1/base-libraries/upsert', { method: 'POST', body: JSON.stringify(seedLibraryFace) });
    await api('/api/v1/base-libraries/upsert', { method: 'POST', body: JSON.stringify(seedLibraryOcr) });
    await api('/api/v1/base-libraries/mappings/upsert', {
      method: 'POST',
      body: JSON.stringify(Object.assign({}, baseMapping, {
        capability: 'face',
        library_id: 'lib-face-ui',
        library_version: '2026.03',
        execution_hints: { model_uri: 'file:///runtime/models/face-detector-ui.rknn' },
      })),
    });
    await api('/api/v1/base-libraries/mappings/upsert', {
      method: 'POST',
      body: JSON.stringify(Object.assign({}, baseMapping, {
        capability: 'ocr',
        library_id: 'lib-ocr-ui',
        library_version: '2026.03',
        execution_hints: { model_uri: 'file:///runtime/models/ocr-detector-ui.rknn' },
      })),
    });
    await api('/api/v1/runtime/telemetry', {
      method: 'POST',
      body: JSON.stringify({
        tenant_id: 't1',
        site_id: 's1',
        box_id: 'rk3588-box-1',
        device_id: 'cam-ui-demo',
        fps_in: 12.0,
      }),
    });
    await api('/api/v1/inference/results', {
      method: 'POST',
      body: JSON.stringify({
        schema_version: 'rk_decode_demo_result/v1',
        workload: {
          tenant_id: 't1',
          site_id: 's1',
          box_id: 'rk3588-box-1',
          device_id: 'cam-ui-demo',
          capability: 'face',
          algorithm_id: 'face-detector-ui',
          algorithm_version: '1.0.0',
          base_library_id: 'lib-face-ui',
          base_library_version: '2026.03',
          stream_url: 'rtsp://10.0.0.200/live',
        },
        decode: { ok: true, detail: 'decoded_first_frame', coding: 'h264', pixel_format: 'nv12', width: 1920, height: 1080 },
        rga: { requested: true, ok: true, detail: 'letterboxed', output_width: 640, output_height: 640, output_channels: 3, scaled_width: 640, scaled_height: 360, pad_x: 0, pad_y: 140, scale: 0.5 },
        sampling: { selected_frame_index: 1, frames_per_sample: 1, requested_sample_count: 4, sampled_frame_count: 4 },
        inference: {
          requested: true,
          ok: true,
          detail: 'ok',
          detections: [
            { class_id: 0, class_name: 'person', confidence: 0.98, left: 120, top: 80, right: 360, bottom: 520 },
            { class_id: 1, class_name: 'badge', confidence: 0.87, left: 420, top: 160, right: 520, bottom: 320 },
          ],
        },
      }),
    });
    showToast('Demo 数据已注入', 'success');
    await refreshAll({ silent: true });
    const plan = await api('/api/v1/inference/plan', {
      method: 'POST',
      body: JSON.stringify({ budget: 100 }),
    });
    renderPlan(plan);
  }

  function bindEvents() {
    refs.navTabs.forEach((node) => {
      node.addEventListener('click', () => setTab(node.dataset.tab));
    });
    refs.issueTokenBtn.addEventListener('click', async () => {
      try {
        await issueToken();
      } catch (error) {
        showToast('签发失败: ' + error.message, 'danger');
      }
    });
    refs.refreshAllBtn.addEventListener('click', async () => {
      try {
        await refreshAll({ silent: false });
      } catch (error) {
        showToast('刷新失败: ' + error.message, 'danger');
      }
    });
    refs.seedDemoBtn.addEventListener('click', async () => {
      try {
        await seedDemoData();
      } catch (error) {
        showToast('注入失败: ' + error.message, 'danger');
      }
    });
    refs.deviceForm.addEventListener('submit', async (event) => {
      try {
        await submitDeviceForm(event);
      } catch (error) {
        showToast('注册设备失败: ' + error.message, 'danger');
      }
    });
    refs.capabilityForm.addEventListener('submit', async (event) => {
      try {
        await submitCapabilityForm(event);
      } catch (error) {
        showToast('更新能力失败: ' + error.message, 'danger');
      }
    });
    refs.algorithmForm.addEventListener('submit', async (event) => {
      try {
        await submitAlgorithmForm(event);
      } catch (error) {
        showToast('保存算法失败: ' + error.message, 'danger');
      }
    });
    refs.libraryForm.addEventListener('submit', async (event) => {
      try {
        await submitLibraryForm(event);
      } catch (error) {
        showToast('保存底库失败: ' + error.message, 'danger');
      }
    });
    refs.mappingForm.addEventListener('submit', async (event) => {
      try {
        await submitMappingForm(event);
      } catch (error) {
        showToast('保存映射失败: ' + error.message, 'danger');
      }
    });
    refs.planForm.addEventListener('submit', async (event) => {
      try {
        await submitPlanForm(event);
      } catch (error) {
        showToast('生成计划失败: ' + error.message, 'danger');
      }
    });
    refs.resultsTable.addEventListener('click', (event) => {
      const target = event.target.closest('[data-result-id]');
      if (target) {
        renderResultDetailById(target.dataset.resultId);
      }
    });
  }

  function startRefreshLoop() {
    refs.apiBaseLabel.textContent = window.location.origin;
    refs.refreshState.textContent = '15s 自动刷新';
    if (state.refreshTimer) {
      window.clearInterval(state.refreshTimer);
    }
    state.refreshTimer = window.setInterval(() => {
      refreshAll({ silent: true }).catch(() => {});
    }, REFRESH_INTERVAL_MS);
  }

  async function bootstrap() {
    initRefs();
    restoreAuth();
    updateAuthUi();
    bindEvents();
    setTab('overview');
    refs.snapshotJson.textContent = '请先签发 Token 后加载运行时快照';
    refs.metricsGrid.innerHTML = '<article class="mini-card empty-card"><span>等待认证</span><strong>-</strong></article>';
    startRefreshLoop();
    if (state.token) {
      try {
        await refreshAll({ silent: true });
      } catch (_error) {
        showToast('已恢复本地 Token，但首次刷新失败', 'danger');
      }
    }
  }

  window.addEventListener('DOMContentLoaded', bootstrap);
})();
