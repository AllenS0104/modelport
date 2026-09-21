'use strict';
// New API owns accounts, credentials, sessions and authorization. No local user database.
const $ = id => document.getElementById(id);
const brandName = document.body.dataset.brand;
if (!brandName?.trim()) throw new Error('缺少站点品牌配置。');
document.querySelectorAll('[data-brand-name]').forEach(el => { el.textContent = brandName; });
const online = ['http:', 'https:'].includes(location.protocol);
const safeTransport = location.protocol === 'https:' || ['127.0.0.1', 'localhost'].includes(location.hostname);
const names = ['home', 'about', 'models', 'guide', 'keys', 'wallet', 'account', 'register', 'login', 'chat', 'developer', 'operations'];
let status = null, setup = null, checking = false;
let catalog = [], catalogPayload = null, selected = '', catalogReady = false, catalogLoading = false;
let catalogRetryAt = 0, stateRetryAt = 0;
const selectionKey = 'api-sales.h5.selected-model.v1';
try { selected = sessionStorage.getItem(selectionKey) || ''; } catch (_) { /* Storage can be disabled. */ }
function show(name) {
  if (!names.includes(name)) name = 'home';
  document.body.classList.toggle('chat-mode', name === 'chat');
  document.body.classList.toggle('public-mode', ['home', 'about', 'models', 'guide'].includes(name));
  document.querySelectorAll('.panel').forEach(p => { p.hidden = p.id !== name; });
  const navName = ['register', 'login', 'developer'].includes(name) ? 'account' : name === 'chat' ? 'home' : name;
  document.querySelectorAll('.nav, .side-nav button, .public-nav [data-tab]').forEach(b => {
    const target = b.classList.contains('nav') ? navName : name;
    b.classList.toggle('active', b.dataset.tab === target);
    if (b.dataset.tab === target) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });
  document.title = $(name).querySelector('h1').textContent + ' · ' + brandName;
  document.querySelector('.edition').textContent = name === 'operations' ? '仅管理员 · 运维入口' : 'API ONLY · 用户工作台';
  window.scrollTo(0, 0);
  document.dispatchEvent(new Event('workspace-navigation'));
}
function navigate(name) { history.pushState(null, '', '#' + name); show(name); }
document.querySelectorAll('[data-tab]:not([data-tab="login"])').forEach(b => b.addEventListener('click', e => { e.preventDefault(); navigate(b.dataset.tab); }));
window.addEventListener('hashchange', () => show(location.hash.slice(1)));
show(location.hash.slice(1));

async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(path, { credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error', ...options, signal: controller.signal });
    if (response.status === 429) {
      const raw = response.headers.get('Retry-After');
      let seconds = /^\d+$/.test(raw || '') ? Number(raw) : Math.ceil((Date.parse(raw) - Date.now()) / 1000);
      if (!Number.isFinite(seconds) || seconds < 1) seconds = 180;
      const error = new Error(`请求过于频繁，请在 ${seconds} 秒后手动重试。`);
      error.retryAt = Date.now() + seconds * 1000;
      throw error;
    }
    if (response.status === 401 || response.status === 403) {
      const error = new Error('当前无权访问，请登录账户或联系管理员确认开放策略。');
      error.status = response.status;
      throw error;
    }
    if (!response.ok) throw new Error(`服务暂不可用（HTTP ${response.status}），请稍后重试。`);
    const body = await response.json();
    // Never reflect arbitrary auth response text that might echo submitted secrets or account existence.
    if (body.success !== true) throw new Error('接口未返回成功结果，请稍后重试。');
    return body;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时，结果尚未确认。写操作请勿重复提交，请先在原生页面核实。');
    if (error instanceof TypeError || error instanceof SyntaxError) throw new Error('连接失败或接口格式异常，请稍后重试。');
    throw error;
  } finally { clearTimeout(timer); }
}
function registrationGate() {
  if (!online) return '离线文件不能注册或登录，请打开在线本地服务。';
  if (!safeTransport) return '此入口不允许通过非回环 HTTP 提交密码，请使用安全 HTTPS 服务。';
  if (checking) return '正在核实注册开放状态…';
  if (!status || !setup) return '暂时无法确认注册开放状态，请重新检查服务设置。';
  if (setup.status !== true) return '平台尚未准备就绪，需管理员完成初始化后才能注册。';
  if (status.register_enabled !== true) return '管理员尚未开放用户注册。';
  return '';
}
function registrationMessage() {
  const reason = registrationGate();
  return reason || (status.password_register_enabled === false
    ? '密码注册未开放，请在账户注册页查看平台支持的其他方式。'
    : '注册已开放。继续后，在本站账户注册页填写信息并完成所需验证。');
}
function renderGate() {
  const reason = registrationGate();
  $('auth-gate').textContent = registrationMessage();
  const registrationLink = $('register-continue');
  registrationLink.setAttribute('aria-disabled', String(Boolean(reason)));
  if (reason) registrationLink.removeAttribute('href');
  else registrationLink.setAttribute('href', '/register');
  $('login-state').textContent = !online ? '离线不可登录。' : !status || !setup ? '尚未确认服务状态，请稍后重试。' : setup.status !== true ? '平台尚未准备就绪，请等待管理员完成初始化。' : status.password_login_enabled === false ? '密码登录未开放；请在登录页查看支持的其他方式。' : '请使用你在本站注册的账户登录，并完成所需安全验证。';
  document.dispatchEvent(new Event('workspace-state'));
}
async function loadState() {
  if (!online || checking) { renderGate(); return; }
  if (Date.now() < stateRetryAt) { $('auth-gate').textContent = '服务限流等待中，请按提示时间后重试。'; return; }
  checking = true; status = null; setup = null; renderGate(); $('state-refresh').disabled = true;
  try {
    const results = await Promise.allSettled([api('/api/status'), api('/api/setup')]);
    const failures = results.filter(r => r.status === 'rejected');
    if (failures.length) { stateRetryAt = Math.max(...failures.map(r => r.reason.retryAt || 0)); throw failures[0].reason; }
    status = results[0].value.data; setup = results[1].value.data;
    if (!status || typeof setup?.status !== 'boolean') throw new Error('设置接口格式异常，不能确认注册开放状态。');
    $('service-state').textContent = '平台服务已响应';
    $('setup-state').textContent = setup.status ? '系统已初始化' : '等待管理员初始化';
    $('status-description').textContent = '状态来自平台实时接口；账户权限和实际费用由服务端校验。';
  } catch (error) {
    status = null; setup = null;
    $('service-state').textContent = '服务状态未核实'; $('setup-state').textContent = '注册暂不可用'; $('status-description').textContent = error.message;
  } finally {
    checking = false; $('state-refresh').disabled = false; renderGate();
    if (setup?.status === true && shouldRestoreSession()) checkSession();
  }
}
$('state-refresh').addEventListener('click', loadState);

function rememberSelection() {
  try { if (selected) sessionStorage.setItem(selectionKey, selected); else sessionStorage.removeItem(selectionKey); }
  catch (_) { $('selection-note').textContent = '浏览器禁用了会话存储，刷新后需重新选择。'; }
}
function money(value) { return Number.isFinite(value) && value >= 0 ? new Intl.NumberFormat('en-US', { maximumSignificantDigits: 8 }).format(value) : '待确认'; }
function modelGroups(model) {
  return model.enable_groups?.includes('all') ? Object.keys(catalogPayload?.usable_group || {}) : model.enable_groups || [];
}
function priceText(model) {
  if (model.billing_mode || model.billing_expr || model.billing_plugin_variants?.length) return '动态/分层计费：请在原生价目查看规则，不换算为固定单价。';
  const groups = modelGroups(model).filter(group => !$('catalog-group').value || group === $('catalog-group').value);
  const finite = v => typeof v === 'number' && Number.isFinite(v) && v >= 0;
  const lines = groups.map(group => {
    const ratio = catalogPayload.group_ratio?.[group];
    if (!finite(ratio)) return `${group}：价格待确认（缺少分组倍率）`;
    if (model.quota_type === 1 && finite(model.model_price)) return `${group}：USD ${money(model.model_price * ratio)} / 次`;
    if (model.quota_type === 0 && finite(model.model_ratio)) {
      const input = model.model_ratio * 2 * ratio;
      let text = `${group}：输入 USD ${money(input)} / 百万 token；输出 ${finite(model.completion_ratio) ? 'USD ' + money(input * model.completion_ratio) : '待确认'} / 百万 token`;
      if (finite(model.cache_ratio)) text += `；缓存读取 USD ${money(input * model.cache_ratio)} / 百万 token`;
      if (finite(model.create_cache_ratio)) text += `；缓存写入 USD ${money(input * model.create_cache_ratio)} / 百万 token`;
      return text;
    }
    return `${group}：价格待确认`;
  });
  return lines.join('\n') || '价格待确认（目录未提供可用分组）';
}
function renderExample() {
  const model = catalogReady ? catalog.find(m => m.model_name === selected) : null;
  $('selected-model').textContent = selected || '尚未选择模型';
  $('example').textContent = '';
  $('example').hidden = true;
  if (!online || !safeTransport) { $('example-state').textContent = '请通过 HTTPS 或本机回环地址打开平台，再获取接入示例。'; return; }
  if (!selected) { $('example-state').textContent = '手动选择模型后生成示例，不默认替你选模型。'; return; }
  if (!model) { $('example-state').textContent = catalogReady ? '所选模型当前不可用：已保留原 ID，停止生成示例，不会静默替换。请手动选择其他模型。' : '尚未重新确认模型可用性，示例已停用。不会静默替换所选 ID。'; return; }
  const endpoints = model.supported_endpoint_types || [];
  let endpoint, body;
  if (endpoints.includes('openai')) { endpoint = '/chat/completions'; body = { model: selected, messages: [{ role: 'user', content: 'Hello' }] }; }
  else if (endpoints.includes('openai-response')) { endpoint = '/responses'; body = { model: selected, input: 'Hello' }; }
  else if (endpoints.includes('embeddings')) { endpoint = '/embeddings'; body = { model: selected, input: 'Hello' }; }
  else if (endpoints.includes('image-generation')) { endpoint = '/images/generations'; body = { model: selected, prompt: 'A landscape' }; }
  else { $('example-state').textContent = '该目录未声明受支持的 OpenAI 兼容端点；不生成可能错误的请求。请查看原生文档。'; return; }
  $('example-state').textContent = '请求模板（不自动执行）：Authorization 是不可用占位符。目录可见不代表你的 Key 已获授权或上游在线。';
  // HTTP text rather than shell interpolation: model IDs cannot become executable shell input.
  $('example').textContent = `POST ${location.origin}/v1${endpoint}\nAuthorization: Bearer <YOUR_OWN_API_KEY>\nContent-Type: application/json\n\n${JSON.stringify(body, null, 2)}`;
  $('example').hidden = false;
}
function renderCatalog() {
  const groupSelect = $('catalog-group'), groupValue = groupSelect.value;
  const groupNames = [...new Set(catalog.flatMap(modelGroups))].sort();
  groupSelect.replaceChildren(new Option('全部可见分组', ''), ...groupNames.map(group => new Option(group, group)));
  // Preserve a removed filter rather than silently broadening a user's price view.
  if (groupValue && !groupNames.includes(groupValue)) groupSelect.append(new Option(groupValue + '（当前无可见模型）', groupValue));
  groupSelect.value = groupValue;
  const select = $('model-select'); select.replaceChildren();
  const placeholder = document.createElement('option'); placeholder.value = ''; placeholder.textContent = catalog.length ? '请手动选择模型' : '暂无可选模型'; select.append(placeholder);
  for (const model of catalog) { const option = document.createElement('option'); option.value = model.model_name; option.textContent = model.model_name; select.append(option); }
  if (selected && !catalog.some(m => m.model_name === selected)) { const missing = document.createElement('option'); missing.value = selected; missing.textContent = selected + '（当前不可用）'; missing.disabled = true; select.append(missing); }
  select.value = selected;
  select.disabled = !catalogReady || catalog.length === 0;
  $('model-list').replaceChildren();
  const query = $('catalog-search').value.trim().toLocaleLowerCase();
  const visible = catalog.filter(model => model.model_name.toLocaleLowerCase().includes(query) &&
    (!groupValue || modelGroups(model).includes(groupValue)));
  $('catalog-filter-state').textContent = catalogReady
    ? `显示 ${visible.length} / ${catalog.length} 个模型` + (visible.length ? '' : '，没有匹配项。')
    : '目录尚未核实，暂不显示匹配结果。';
  for (const model of visible) {
    const card = document.createElement('article'); card.className = 'card';
    const title = document.createElement('h3'); title.textContent = model.model_name; title.className = 'model-id';
    const price = document.createElement('p'); price.className = 'small price'; price.textContent = priceText(model);
    const button = document.createElement('button'); button.className = 'btn full spaced'; button.textContent = selected === model.model_name ? '已选择' : '选择此模型'; button.setAttribute('aria-pressed', String(selected === model.model_name));
    button.addEventListener('click', () => { selected = model.model_name; rememberSelection(); renderCatalog(); $('selection-card').scrollIntoView({ block: 'start' }); });
    card.append(title, price, button); $('model-list').append(card);
  }
  renderExample();
  document.dispatchEvent(new Event('workspace-state'));
}
async function loadCatalog() {
  if (!online || catalogLoading) return;
  if (Date.now() < catalogRetryAt) { $('catalog-state').textContent = '目录限流等待中，请按提示时间后重试。'; return; }
  catalogLoading = true; catalogReady = false; catalog = []; renderCatalog();
  $('catalog-refresh').disabled = true; $('catalog-state').textContent = '正在读取真实可见模型目录…';
  try {
    const result = await api('/api/pricing');
    if (!Array.isArray(result.data) || result.data.some(m => !m || typeof m.model_name !== 'string' || !m.model_name)) throw new Error('模型目录格式异常，未启用选择或示例。');
    catalogPayload = result;
    catalog = [...new Map(result.data.map(m => [m.model_name, m])).values()]; catalogReady = true;
    $('catalog-state').textContent = catalog.length ? `已读取当前访客可见目录：${catalog.length} 个模型。价格以接口返回的分组为准。` : '暂无可见模型。尚无可选项，不展示虚构销售模型或价格。';
  } catch (error) { catalogRetryAt = error.retryAt || 0; $('catalog-state').textContent = error.message; }
  finally { catalogLoading = false; $('catalog-refresh').disabled = false; renderCatalog(); }
}
$('model-select').addEventListener('change', () => { selected = $('model-select').value; rememberSelection(); renderCatalog(); });
$('catalog-refresh').addEventListener('click', loadCatalog);
$('catalog-search').addEventListener('input', renderCatalog);
$('catalog-group').addEventListener('change', renderCatalog);
$('clear-selection').addEventListener('click', () => { selected = ''; rememberSelection(); renderCatalog(); });
if (online) { loadState(); loadCatalog(); }
else {
  $('service-state').textContent = '离线展示 · 未连接后台'; $('setup-state').textContent = '可浏览交互，不可办理业务';
  $('status-description').textContent = '离线 HTML 不能真实注册、登录或获取模型；请打开在线本地服务。';
  $('catalog-state').textContent = '离线模式：未连接模型目录，没有可选模型。';
  $('state-refresh').disabled = true; $('catalog-refresh').disabled = true;
  document.querySelectorAll('[data-native]').forEach(a => { a.removeAttribute('href'); a.setAttribute('aria-disabled', 'true'); });
  renderGate(); renderCatalog();
}

// Native login owns credentials and refresh cookies. Access tokens live only in memory.
let authBundle = null, authorizedModels = [], sessionPromise = null, sessionEpoch = 0;
let sessionAttempted = false;
let sessionAnonymous = false;
let sessionNote = '尚未核实登录会话', sessionRetryAt = 0;
let chatController = null, chatAbortReason = '';
let chatSessions = [], activeChat = null, chatSequence = 0, chatBusy = false;
let operationsLoading = false, operationsGeneration = 0, operationsRetryAt = 0;
const accountEntries = [...document.querySelectorAll('[data-tab="login"], #native-login')].map(element => ({
  element, label: element.textContent, href: element.getAttribute('href'),
}));
for (const { element } of accountEntries) {
  element.addEventListener('click', event => {
    if (element.getAttribute('aria-disabled') === 'true') { event.preventDefault(); return; }
    if (element.dataset.sessionAction === 'retry') { event.preventDefault(); checkSession(); return; }
    if (element.tagName === 'A') return;
    if (authBundle) location.assign('/security');
    else navigate('login');
  });
}
function renderAccountEntries() {
  const authenticated = Boolean(authBundle);
  const pending = !authenticated && (checking || Boolean(sessionPromise));
  const retry = sessionAttempted && !authenticated && !pending && !sessionAnonymous && online && safeTransport && setup?.status === true;
  for (const { element, label, href } of accountEntries) {
    const disabled = pending || (element.id === 'native-login' && (!online || !safeTransport));
    element.textContent = authenticated ? '账户与安全' : pending ? '正在确认账户…' : retry ? '重新确认账户' : label;
    element.dataset.sessionAction = retry ? 'retry' : '';
    element.setAttribute('aria-disabled', String(disabled));
    if (element.tagName === 'BUTTON') element.disabled = disabled;
    else if (disabled) element.removeAttribute('href');
    else element.setAttribute('href', authenticated ? '/security' : retry ? '#login' : href);
  }
  document.querySelectorAll('[data-tab="register"], #register-continue, [data-guest-only]').forEach(element => {
    element.hidden = authenticated || pending;
  });
  document.querySelectorAll('[data-session-label]').forEach(element => {
    element.textContent = authenticated ? '已登录 · 账户已连接' : pending ? '正在确认账户…' : sessionAnonymous ? '未登录' : '登录状态待确认';
  });
  $('login-title').textContent = authenticated ? '我的账户' : '登录账户';
  if (!$('login').hidden) document.title = $('login-title').textContent + ' · ' + brandName;
  $('auth-gate').textContent = authenticated ? '你已登录，无需重复注册。可直接进入工作台或管理账户安全。' : registrationMessage();
  if (authenticated || retry || sessionAnonymous) $('login-state').textContent = sessionNote;
  else if (pending) $('login-state').textContent = '正在确认当前账户，请稍候…';
  $('session-refresh').textContent = sessionPromise ? '正在检查…' : authenticated ? '刷新权限' : '检查登录与权限';
  $('chat-account-hint').textContent = authenticated ? '手动选择当前分组获准的模型。' : pending ? '正在确认账户与模型权限…' : retry ? '请重新确认账户，再选择模型。' : '先登录，再手选当前分组获准的模型。';
}
function clearSession(note, anonymous = false) {
  sessionEpoch++;
  sessionAnonymous = anonymous;
  authBundle = null; authorizedModels = []; sessionNote = note;
  clearOperations();
  chatAbortReason = '登录状态发生变化，已停止接收。请在原生用量记录核实结算。';
  chatController?.abort();
  chatSessions = []; activeChat = null; $('chat-input').value = '';
  renderChat();
}
function initializeGuide() {
  const apiBase = online && safeTransport ? location.origin + '/v1' : '';
  document.querySelectorAll('[data-api-base]').forEach(el => {
    el.textContent = apiBase || '请从平台 HTTPS 域名或本机回环入口获取 Base URL';
  });
  document.querySelectorAll('[data-endpoint-note]').forEach(el => {
    el.textContent = !apiBase ? '离线或非安全来源不提供可发送凭据的地址。' :
      location.protocol === 'http:' ? '当前是本机/SSH 隧道地址，仅当前设备可用。正式上线后这里会自动使用平台 HTTPS 域名。' :
      '地址跟随当前站点域名。发送凭据前请核对平台正式域名；HTTPS 不代表模型服务已经开通。';
  });
  $('guide-env').textContent = `# Bash / Linux / macOS
  export PLATFORM_BASE_URL="${apiBase || 'https://YOUR_PLATFORM_DOMAIN/v1'}"
  export PLATFORM_MODEL="REPLACE_WITH_ALLOWED_MODEL"
  # PLATFORM_API_KEY 通过受保护环境注入，不在命令历史写真实 Key

  # PowerShell / Windows
  $env:PLATFORM_BASE_URL = "${apiBase || 'https://YOUR_PLATFORM_DOMAIN/v1'}"
  $env:PLATFORM_MODEL = "REPLACE_WITH_ALLOWED_MODEL"`;
  if (!online) document.querySelectorAll('[data-sample-download]').forEach(el => {
    el.removeAttribute('href'); el.setAttribute('aria-disabled', 'true');
  });
  let guideLoading = false, guideReady = false;
  async function loadGuide() {
    if (guideLoading || guideReady) return;
    if (!online) { $('guide-load-state').textContent = '离线文件不包含下载示例，请从在线平台打开教程。'; return; }
    guideLoading = true;
    $('guide-load-state').textContent = '正在读取公开示例文件，不会调用模型…';
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 12000);
    try {
      const samples = await Promise.all(['chat.py', 'chat.mjs', 'request.json'].map(async name => {
        const response = await fetch('examples/' + name, {
          credentials: 'omit', mode: 'same-origin', redirect: 'error', signal: controller.signal,
        });
        if (!response.ok) throw new Error('示例文件读取失败，请刷新页面或检查部署文件。');
        const text = await response.text();
        if (!text.trim() || text.length > 32000) throw new Error('示例文件格式异常，未展示为可执行教程。');
        return text;
      }));
      ['guide-python', 'guide-node', 'guide-request'].forEach((id, index) => { $(id).textContent = samples[index]; });
      guideReady = true;
      $('guide-load-state').textContent = '示例已就绪。请先设置自己的环境变量；运行时才会发起收费请求。';
    } catch (error) {
      $('guide-load-state').textContent = error.name === 'AbortError' ? '读取示例超时，请刷新页面后重试。' :
        error instanceof TypeError ? '无法连接示例文件，请检查网络后刷新页面。' : error.message;
    } finally { clearTimeout(timer); guideLoading = false; }
  }
  document.addEventListener('workspace-navigation', () => { if (!$('guide').hidden) loadGuide(); });
  if (!$('guide').hidden) loadGuide();
}
function shouldRestoreSession() {
  if (!online || !safeTransport) return false;
  const publicPage = ['home', 'about', 'models', 'guide'].some(name => !$(name).hidden);
  // This public-page optimization never grants identity; account pages still ask the server.
  return !publicPage || /(?:^|;\s*)new_api_has_session=1(?:;|$)/.test(document.cookie);
}
async function checkSession() {
  if (!online || !safeTransport || setup?.status !== true) return false;
  if (sessionPromise) return sessionPromise;
  if (Date.now() < sessionRetryAt) { sessionNote = '会话检查限流中，请稍后手动重试。'; renderChat(); return false; }
  sessionAttempted = true;
  const epoch = sessionEpoch;
  const run = async () => {
    try {
      const refresh = async () => {
        const result = await api('/api/user/auth/refresh', {
          method: 'POST',
          headers: authBundle ? { 'X-Auth-Session': authBundle.session.sid } : {},
        });
        const bundle = result.data;
        if (typeof bundle?.access_token !== 'string' || !bundle.access_token ||
            bundle.token_type !== 'Bearer' || !Number.isFinite(bundle.access_expires_at) ||
            bundle.access_expires_at <= Date.now() / 1000 ||
            !Number.isInteger(bundle.user?.id) || bundle.user.id <= 0 ||
            typeof bundle.user.group !== 'string' || !bundle.user.group ||
            typeof bundle.session?.sid !== 'string' || !bundle.session.sid || bundle.session.current !== true) {
          throw new Error('原生会话响应格式异常，请重新登录。');
        }
        if (epoch !== sessionEpoch) return false;
        if (authBundle && (authBundle.user.id !== bundle.user.id || authBundle.session.sid !== bundle.session.sid)) {
          clearSession('账户已变化，请重新核实会话后手动选择模型。');
          return false;
        }
        authBundle = bundle;
        return true;
      };
      // Share the native application's lock to avoid racing rotating refresh cookies.
      if (!authBundle || authBundle.access_expires_at < Date.now() / 1000 + 60) {
        const valid = navigator.locks
          ? await navigator.locks.request('new-api:auth-refresh', { mode: 'exclusive' }, refresh)
          : await refresh();
        if (!valid) return false;
      }
      const headers = { Authorization: `Bearer ${authBundle.access_token}` };
      const self = (await api('/api/user/self', { headers })).data;
      if (epoch !== sessionEpoch) return false;
      if (self?.id !== authBundle.user.id || typeof self.group !== 'string' || !self.group) {
        throw new Error('账户身份未确认，请重新登录。');
      }
      const models = (await api('/api/user/models?group=' + encodeURIComponent(self.group), { headers })).data;
      if (epoch !== sessionEpoch) return false;
      if (!Array.isArray(models) || models.some(m => typeof m !== 'string' || !m)) throw new Error('账户模型权限响应异常。');
      authBundle.user = self; authorizedModels = models;
      sessionNote = `已登录：${self.username} · 当前计费分组：${self.group}`;
      return true;
    } catch (error) {
      if (epoch !== sessionEpoch) return false;
      sessionRetryAt = error.retryAt || 0;
      clearSession(error.status === 401 ? '尚未登录或会话已失效，请登录账户。' : error.message, error.status === 401);
      return false;
    }
  };
  sessionPromise = run();
  renderChat();
  try { return await sessionPromise; }
  finally { sessionPromise = null; renderChat(); }
}
$('session-refresh').addEventListener('click', checkSession);
function onSessionEvent(event) {
  if (!event || !['authenticated', 'signed_out'].includes(event.kind) ||
      typeof event.sid !== 'string' || !Number.isFinite(event.timestamp) ||
      Math.abs(Date.now() - event.timestamp) >= 60000) return;
  if (event.kind === 'signed_out' && authBundle && event.sid !== authBundle.session.sid) return;
  clearSession('其他页面的登录状态已改变。请检查会话并重新选择模型。', event.kind === 'signed_out');
  selected = ''; rememberSelection(); renderCatalog();
}
if (online && typeof BroadcastChannel !== 'undefined') {
  const sessionChannel = new BroadcastChannel('new-api:auth-session');
  sessionChannel.addEventListener('message', event => onSessionEvent(event.data));
} else if (online) {
  window.addEventListener('storage', event => {
    if (event.key !== 'new-api:auth-session:event' || !event.newValue) return;
    try { onSessionEvent(JSON.parse(event.newValue)); }
    catch (_) { clearSession('会话同步消息异常，请重新核实登录。'); }
  });
}
window.addEventListener('pageshow', event => { if (event.persisted) checkSession(); });
window.addEventListener('focus', () => { if (authBundle && !chatBusy) checkSession(); });
function currentChat() { return chatSessions.find(item => item.id === activeChat); }
function chatBlockReason() {
  if (!online) return '离线展示：不能登录、获取模型或发送消息。';
  if (!safeTransport) return '仅支持 HTTPS 或回环 HTTP，不通过不安全网络发送会话或消息。';
  if (checking || !setup) return '服务状态未核实；未建立可验证的登录会话，不能发送。';
  if (setup.status !== true) return '管理员尚未初始化；未建立登录会话。真实模型未就绪，发送不可用。';
  if (sessionPromise) return '正在核实登录会话与模型权限…';
  if (!authBundle) return sessionNote;
  if (!catalogReady) return '目录尚未核实，不能发送。';
  if (!selected) return '请手动选择模型，不自动替你选择或切换。';
  const model = catalog.find(m => m.model_name === selected);
  if (!model || !authorizedModels.includes(selected)) return '所选模型不在当前账户分组的可用范围，请重新手选；不会静默替换。';
  if (!model.supported_endpoint_types?.includes('openai')) return '此模型不支持本工作台的 Chat Completions 接口，请使用对应 API。';
  return '';
}
function newChat() {
  if (chatBusy) return;
  const item = { id: ++chatSequence, title: `临时会话 ${chatSequence}`, draft: '', messages: [] };
  chatSessions.push(item); activeChat = item.id;
  $('chat-input').value = ''; renderChat(); closeHistory(); $('chat-input').focus();
}
function renderHistory() {
  for (const id of ['history-list', 'sidebar-history']) {
    $(id).replaceChildren();
    for (const item of chatSessions) {
      const button = document.createElement('button'); button.className = 'btn full';
      button.textContent = item.title; button.setAttribute('aria-current', String(item.id === activeChat));
      button.disabled = chatBusy;
      button.addEventListener('click', () => {
        if (chatBusy) return;
        activeChat = item.id; $('chat-input').value = item.draft;
        navigate('chat'); renderChat(); closeHistory(); $('chat-input').focus();
      });
      $(id).append(button);
    }
  }
  $('history-empty').hidden = chatSessions.length > 0;
  $('sidebar-history-empty').hidden = chatSessions.length > 0;
  $('sidebar-new').disabled = chatBusy;
  $('history-clear').disabled = chatBusy || !chatSessions.length;
  $('history-new').disabled = chatBusy;
}
function renderChat() {
  const modelSelect = $('chat-model');
  modelSelect.replaceChildren(...[...$('model-select').options].map(option => option.cloneNode(true)));
  for (const option of modelSelect.options) {
    if (option.value && authBundle && (!authorizedModels.includes(option.value) ||
        !catalog.find(m => m.model_name === option.value)?.supported_endpoint_types?.includes('openai'))) option.disabled = true;
  }
  modelSelect.value = selected; modelSelect.disabled = $('model-select').disabled || chatBusy;
  const messages = currentChat()?.messages || [];
  $('chat-messages').replaceChildren();
  for (const message of messages) {
    const article = document.createElement('article');
    article.className = 'chat-message ' + (message.role === 'user' ? 'user' : 'assistant');
    const title = document.createElement('h3'); title.textContent = message.role === 'user' ? '你' : '助手';
    const text = document.createElement('p'); text.textContent = message.content;
    article.append(title, text);
    if (message.state) { const state = document.createElement('small'); state.textContent = message.state; article.append(state); }
    $('chat-messages').append(article);
  }
  $('chat-empty').hidden = messages.length > 0;
  $('chat-messages').setAttribute('aria-busy', String(chatBusy));
  $('chat-gate').textContent = chatBlockReason() || '发送将按当前分组实际用量计费。停止接收不保证免单或上游立即停止；以原生账单为准。';
  $('chat-send').disabled = Boolean(chatBlockReason()) || chatBusy || !$('chat-input').value.trim();
  $('chat-send').hidden = chatBusy;
  $('chat-stop').hidden = !chatBusy; $('chat-stop').disabled = !chatBusy;
  $('chat-input').disabled = chatBusy; $('chat-new').disabled = chatBusy;
  $('chat-local-state').textContent = chatBusy ? '请求处理中 · 不自动重试' : '临时会话 · 刷新清空';
  $('chat-session').textContent = sessionNote;
  $('session-refresh').disabled = !online || !safeTransport || setup?.status !== true || Boolean(sessionPromise) || chatBusy;
  renderAccountEntries();
  $('sidebar-session').textContent = authBundle ? `${authBundle.user.username} · ${authBundle.user.group}` : '同一账户，同一账本';
  renderHistory();
  renderOperationsAccess();
}
function closeHistory() { $('chat-history').close(); $('history-open').setAttribute('aria-expanded', 'false'); }
$('history-open').addEventListener('click', () => { renderHistory(); $('chat-history').showModal(); $('history-open').setAttribute('aria-expanded', 'true'); });
$('history-close').addEventListener('click', closeHistory);
$('chat-history').addEventListener('close', () => $('history-open').setAttribute('aria-expanded', 'false'));
$('chat-history').addEventListener('click', event => { if (event.target === $('chat-history') && event.clientX > $('chat-history').getBoundingClientRect().right) closeHistory(); });
$('chat-new').addEventListener('click', newChat);
$('sidebar-new').addEventListener('click', () => { navigate('chat'); newChat(); });
$('history-new').addEventListener('click', newChat);
$('history-clear').addEventListener('click', () => {
  if (chatBusy || !confirm('清空本标签页全部临时会话与草稿？此操作无法撤销。')) return;
  chatSessions = []; activeChat = null; $('chat-input').value = ''; renderChat();
});
$('chat-input').addEventListener('input', () => {
  if (!currentChat()) {
    chatSessions.push({ id: ++chatSequence, title: `临时会话 ${chatSequence}`, draft: '', messages: [] }); activeChat = chatSequence;
  }
  currentChat().draft = $('chat-input').value; renderChat();
});
$('chat-model').addEventListener('change', () => { selected = $('chat-model').value; rememberSelection(); renderCatalog(); });
async function readChatStream(response, assistant, signal) {
  if (!response.headers.get('Content-Type')?.includes('text/event-stream') || !response.body) {
    throw new Error('服务未返回预期的事件流，未将响应视为成功。请核实用量记录。');
  }
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '', done = false, usage = null;
  const consume = block => {
    const data = block.split(/\r?\n/).filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).replace(/^ /, '')).join('\n');
    if (!data) return;
    if (data.trim() === '[DONE]') { done = true; return; }
    let event;
    try { event = JSON.parse(data); }
    catch (_) { throw new Error('模型事件流格式异常；未完成的回答不会加入下一轮上下文。'); }
    if (!event || typeof event !== 'object' || event.error) throw new Error('模型返回错误；请在原生用量记录核实请求和费用。');
    const delta = event.choices?.[0]?.delta;
    if (delta?.tool_calls?.length) throw new Error('本工作台暂不执行工具调用，请使用开发者 API。');
    if (typeof delta?.content === 'string') assistant.content += delta.content;
    if (typeof delta?.reasoning_content === 'string') assistant.state = '模型推理中…';
    if (event.usage) usage = event.usage;
    if (assistant.content.length > 250000) throw new Error('回答超过本工作台显示上限，已停止接收；请核实账单。');
    renderChat();
    $('chat-stage').scrollTop = $('chat-stage').scrollHeight;
  };
  try {
    while (!done) {
      const chunk = await reader.read();
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
      let boundary;
      while (!done && (boundary = /\r?\n\r?\n/.exec(buffer))) {
        const block = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        consume(block);
      }
      if (buffer.length > 1000000) throw new Error('模型事件超出上限，已停止接收。');
      if (chunk.done) {
        if (buffer.trim() && !done) consume(buffer);
        if (!done) throw new Error('连接在完成标记前断开；回答不完整，请核实账单后再决定是否重试。');
      }
    }
    if (!assistant.content) throw new Error('请求结束但没有可显示的文本回答，请核实原生用量记录。');
    return usage;
  } finally {
    try { await reader.cancel(); } finally { reader.releaseLock(); }
  }
}
$('chat-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (chatBusy || chatBlockReason() || !$('chat-input').value.trim()) return;
  const item = currentChat(), model = selected, draft = $('chat-input').value.trim(), epoch = sessionEpoch;
  if (!item) return;
  chatBusy = true; chatAbortReason = ''; chatController = new AbortController();
  const controller = chatController;
  let assistant = null, user = null, timeout = null;
  renderChat();
  try {
    if (!await checkSession() || epoch !== sessionEpoch || controller.signal.aborted) return;
    if (selected !== model) throw new Error('准备请求期间所选模型发生变化，请确认后重新发送。');
    if (chatBlockReason()) throw new Error(chatBlockReason());
    const messages = item.messages.filter(m => m.complete).map(m => ({ role: m.role, content: m.content }));
    messages.push({ role: 'user', content: draft });
    if (JSON.stringify(messages).length > 100000) throw new Error('会话上下文过长，请新建会话；不会静默删减上下文。');
    user = { role: 'user', content: draft, complete: false };
    assistant = { role: 'assistant', content: '', state: '正在连接…', complete: false };
    item.messages.push(user, assistant);
    item.title = draft.slice(0, 30); item.draft = ''; $('chat-input').value = '';
    renderChat();
    timeout = setTimeout(() => {
      chatAbortReason = '请求超过 180 秒，已停止接收；请先核实账单，不自动重试。';
      controller.abort();
    }, 180000);
    const response = await fetch('/pg/chat/completions', {
      method: 'POST', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authBundle.access_token}` },
      body: JSON.stringify({ model, group: authBundle.user.group, messages, stream: true, max_tokens: 1024, stream_options: { include_usage: true } }),
      signal: controller.signal,
    });
    if (response.status === 401) { clearSession('登录会话已失效，请重新登录。', true); return; }
    if (!response.ok) {
      await response.body?.cancel();
      throw new Error(response.status === 429 ? '请求被限流，未自动重试；请稍后再试。' :
        `调用失败（HTTP ${response.status}）：请核实模型权限、余额或上游状态；不会自动重试。`);
    }
    const usage = await readChatStream(response, assistant, controller.signal);
    if (epoch !== sessionEpoch) return;
    user.complete = true; assistant.complete = true;
    assistant.state = Number.isSafeInteger(usage?.prompt_tokens) && Number.isSafeInteger(usage?.completion_tokens)
      ? `已完成 · 输入 ${usage.prompt_tokens} / 输出 ${usage.completion_tokens} token；费用以原生账单为准`
      : '已完成 · 费用以原生用量记录为准';
  } catch (error) {
    if (epoch !== sessionEpoch) return;
    const message = error.name === 'AbortError' ? chatAbortReason || '已停止接收；上游可能仍计费，请核实账单。'
      : error instanceof TypeError ? '网络连接失败，结果未确认；请核实账单，不自动重试。' : error.message;
    if (assistant) { assistant.state = message; item.draft = draft; $('chat-input').value = draft; }
    else sessionNote = message;
  } finally {
    clearTimeout(timeout);
    chatBusy = false; chatController = null; renderChat();
  }
});
$('chat-stop').addEventListener('click', () => {
  chatAbortReason = '已停止接收；部分回答不会加入下一轮上下文，上游费用以原生账单为准。';
  chatController?.abort();
});
function isOperator() { return Number.isInteger(authBundle?.user.role) && authBundle.user.role >= 10; }
function clearOperations() {
  operationsGeneration++;
  operationsLoading = false;
  $('operations-models').replaceChildren();
  $('operations-state').textContent = '尚未读取观测数据';
}
function renderOperationsAccess() {
  const allowed = isOperator() && online && safeTransport && setup?.status === true;
  document.querySelectorAll('[data-admin-only]').forEach(el => { el.hidden = !allowed; });
  $('operations-content').hidden = !allowed;
  $('operations-gate').textContent = allowed ? '已核实管理员身份；资源权限仍由原生后台逐项校验。' :
    !online ? '离线模式不能读取运维数据。' :
    setup?.status !== true ? '服务未初始化或状态未核实，运维数据不可用。' :
    authBundle ? '此账户不是管理员；客户仅可查看自己的 Key 和消费记录。' : '尚未核实管理员身份，请登录后检查会话。';
  $('operations-session-refresh').disabled = !online || !safeTransport || setup?.status !== true || Boolean(sessionPromise) || chatBusy;
  $('operations-refresh').disabled = !allowed || operationsLoading || Boolean(sessionPromise);
  for (const link of document.querySelectorAll('#operations-content [data-native]')) {
    const [resource, action] = (link.dataset.adminPermission || '').split('.');
    const permitted = allowed && (!resource || authBundle.user.permissions?.admin_permissions?.[resource]?.[action] === true);
    link.setAttribute('aria-disabled', String(!permitted));
    if (permitted) link.setAttribute('href', link.dataset.native);
    else link.removeAttribute('href');
  }
  if (!allowed) clearOperations();
}
async function loadOperations() {
  if (operationsLoading || !isOperator()) return;
  if (Date.now() < operationsRetryAt) { $('operations-state').textContent = '统计接口限流中，请稍后手动重试。'; return; }
  const generation = ++operationsGeneration, epoch = sessionEpoch;
  operationsLoading = true; renderOperationsAccess();
  $('operations-models').replaceChildren();
  $('operations-state').textContent = '正在核实会话并读取最近 24 小时观测…';
  try {
    if (!await checkSession() || !isOperator() || generation !== operationsGeneration) return;
    const result = await api('/api/perf-metrics/summary?hours=24', {
      headers: { Authorization: `Bearer ${authBundle.access_token}` },
    });
    if (epoch !== sessionEpoch || generation !== operationsGeneration || !isOperator()) return;
    const models = result.data?.models;
    if (!Array.isArray(models) || models.some(model =>
      typeof model?.model_name !== 'string' || !model.model_name ||
      !Number.isFinite(model.success_rate) || model.success_rate < 0 || model.success_rate > 100 ||
      !Number.isFinite(model.avg_latency_ms) || model.avg_latency_ms < 0 ||
      !Number.isFinite(model.avg_tps) || model.avg_tps < 0)) throw new Error('运行统计格式异常，未将结果视为健康状态。');
    const observed = new Map(models.map(model => [model.model_name, model]));
    const modelNames = [...new Set([...catalog.map(model => model.model_name), ...observed.keys()])].sort();
    for (const name of modelNames) {
      const model = observed.get(name), row = document.createElement('tr');
      const cells = [name, !model ? '无近期样本 · 未知' : model.success_rate < 100 ? '近期有失败' : '近期请求成功',
        model ? `${money(model.success_rate)}%` : '—', model ? `${money(model.avg_latency_ms)} ms` : '—',
        model ? `${money(model.avg_tps)} token/s` : '—'];
      for (const value of cells) { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); }
      $('operations-models').append(row);
    }
    $('operations-state').textContent = `${new Date().toLocaleString()} 已读取 · ${models.length} 个模型有近期观测。` +
      (models.length ? '聚合历史表现不保证当前可用。' : '暂无调用样本，不宣称模型健康。');
  } catch (error) {
    if (epoch !== sessionEpoch || generation !== operationsGeneration) return;
    operationsRetryAt = error.retryAt || 0;
    if (error.status === 401) clearSession('登录会话已失效，请重新登录。', true);
    else $('operations-state').textContent = error.message;
  } finally {
    if (generation === operationsGeneration) { operationsLoading = false; renderOperationsAccess(); }
  }
}
$('operations-refresh').addEventListener('click', loadOperations);
$('operations-session-refresh').addEventListener('click', checkSession);
document.addEventListener('workspace-state', renderChat);
document.addEventListener('workspace-navigation', closeHistory);
document.addEventListener('workspace-navigation', () => {
  if (!authBundle && !sessionAnonymous && !sessionPromise && shouldRestoreSession()) checkSession();
});
window.addEventListener('pagehide', () => { clearSession('页面已离开，请重新核实登录会话。'); });
renderChat();
initializeGuide();
