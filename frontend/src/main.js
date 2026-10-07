import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

const app = document.getElementById("app");
const state = {
  ready: false,
  user: null,
  view: "board",
  workshops: [],
  board: null,
  picked: null,
  peak: "96",
  err: "",
  msg: "",
  quotas: [],
  quotaFilter: "",
  topup: "1",
  username: "admin",
  password: "123456",
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toLocaleDateString("zh-CN")} ${d.toLocaleTimeString("zh-CN", { hour12: false })}`;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function loadWorkshops(selectId) {
  state.workshops = await api("/api/workshops");
  if (selectId == null) selectId = state.workshops[0]?.id ?? null;
  state.boardWorkshopId = selectId;
}

async function refreshBoard() {
  const qs = state.boardWorkshopId ? `?workshop_id=${state.boardWorkshopId}` : "";
  state.board = await api(`/api/board${qs}`);
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || null;
  }
  render();
}

async function refreshQuotas() {
  const qs = state.quotaFilter ? `?workshop_id=${state.quotaFilter}` : "";
  state.quotas = await api(`/api/quotas${qs}`);
  render();
}

function go(view) {
  state.view = view;
  state.err = "";
  state.msg = "";
  render();
  if (view === "board") refreshBoard().catch((e) => { state.err = e.message; render(); });
  if (view === "blower") refreshQuotas().catch((e) => { state.err = e.message; render(); });
}

function renderLogin() {
  const box = el(`<div class="wrap">
    <h1>骨巷熬胶坊</h1>
    <p>一排熬锅作业台，原生页面，无前端框架。</p>
    <form autocomplete="off">
      <label>用户名
        <input name="u" autocomplete="off" value="${esc(state.username)}" />
      </label>
      <label>密码
        <input name="p" type="password" autocomplete="off" value="${esc(state.password)}" />
      </label>
      <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
      <button>登录</button>
    </form>
    <p class="err">${esc(state.err)}</p>
  </div>`);
  box.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    state.err = "";
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: box.querySelector("[name=u]").value,
          password: box.querySelector("[name=p]").value,
        }),
      });
      localStorage.setItem(TOKEN_KEY, data.access_token);
      state.user = data.user;
      state.ready = true;
      await loadWorkshops();
      go("board");
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  app.append(box);
}

function topBar() {
  const nav = el(`<nav class="topbar">
    <span class="brand">骨巷熬胶坊</span>
    <button class="navbtn" data-v="board">锅位作业台</button>
    <button class="navbtn" data-v="blower">鼓风台</button>
    <span class="spacer"></span>
    <span class="who">${esc(state.user.username)}（${state.user.role === "admin" ? "管理员" : "操作工"}）</span>
    <button class="logout">退出</button>
  </nav>`);
  nav.querySelectorAll(".navbtn").forEach((b) => {
    b.classList.toggle("active", b.dataset.v === state.view);
    b.onclick = () => go(b.dataset.v);
  });
  nav.querySelector(".logout").onclick = () => {
    localStorage.removeItem(TOKEN_KEY);
    location.reload();
  };
  return nav;
}

function workshopOptions(selectedId) {
  return state.workshops
    .map((w) => `<option value="${w.id}" ${w.id === selectedId ? "selected" : ""}>${esc(w.name)}</option>`)
    .join("");
}

function renderBoard(box) {
  const b = state.board;
  const mins = b.remainingMinutes ?? 0;
  const head = el(`<div class="pagehead">
    <h1>${esc(b.workshop)}</h1>
      <p>${esc(b.alley)} · 点锅登记峰值；出胶须最近峰值 ≥ 90℃</p>
      <div class="tools">
        <label class="filter">坊
          <select class="shopfilter">${workshopOptions(b.workshopId)}</select>
        </label>
        <span class="quota ${mins === 0 ? "zero" : ""}">鼓风剩余 <strong>${mins}</strong> 分钟</span>
      </div>
      <div class="row"></div>
      <section class="drawer"></section>
      <p class="ok">${esc(state.msg)}</p>
      <p class="err">${esc(state.err)}</p>
    </div>`);
  head.querySelector(".shopfilter").onchange = async (e) => {
    state.boardWorkshopId = Number(e.target.value);
    state.picked = null;
    try {
      await refreshBoard();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  const row = head.querySelector(".row");
  b.kettles.forEach((k) => {
    const btn = el(`<button class="kettle ${k.status}"><strong>${esc(k.code)}</strong><span>${LABELS[k.status]}</span></button>`);
    btn.onclick = () => {
      state.picked = k;
      render();
    };
    row.append(btn);
  });
  if (state.picked) {
    const d = head.querySelector(".drawer");
    const canHint = mins >= 1 ? "" : `<p class="warn">鼓风剩余 0 分钟：登记将被拦下，峰值不会入库</p>`;
    d.innerHTML = `<h3>${esc(state.picked.code)} · ${LABELS[state.picked.status]}</h3>
      <p>最近峰值：${state.picked.latestPeakC ?? "无"} ℃ · ${state.picked.cookCount} 次
      · 本坊鼓风剩余 <strong>${mins}</strong> 分钟</p>
      <input id="peak" value="${esc(state.peak)}" />
      <button id="log">登记峰值</button>
      <div>
        <button data-s="cold">冷锅</button>
        <button data-s="boiling">熬煮中</button>
        <button data-s="drawn">已出胶</button>
      </div>
      ${canHint}`;
    d.querySelector("#log").onclick = async () => {
      state.err = "";
      state.msg = "";
      state.peak = d.querySelector("#peak").value;
      try {
        const updated = await api(`/api/kettles/${state.picked.id}/cooks`, {
          method: "POST",
          body: JSON.stringify({ peakTempC: Number(state.peak) }),
        });
        state.msg = `已登记，鼓风剩余 ${updated.remainingMinutes ?? 0} 分钟`;
        await refreshBoard();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
    d.querySelectorAll("[data-s]").forEach((btn) => {
      btn.onclick = async () => {
        state.err = "";
        state.msg = "";
        try {
          state.picked = await api(`/api/kettles/${state.picked.id}/status`, {
            method: "POST",
            body: JSON.stringify({ status: btn.dataset.s }),
          });
          state.msg = "锅态已更新（不扣鼓风分钟）";
          await refreshBoard();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
    });
  }
  box.append(head);
}

function renderBlower(box) {
  const isAdmin = state.user.role === "admin";
  const opts = [`<option value="">全部坊</option>`, workshopOptions(Number(state.quotaFilter) || -1)].join("");
  const page = el(`<div class="pagehead">
    <h1>鼓风台</h1>
    <p>整坊鼓风剩余分钟；登记峰值时每分钟抵一次登峰，改锅态不扣分钟。</p>
    <div class="tools">
      <label class="filter">按坊筛
        <select class="quotafilter">${opts}</select>
      </label>
      ${isAdmin ? "" : `<span class="hint">操作工只读；仅管理员可把分钟补回去</span>`}
    </div>
    <table class="quotatable">
      <thead><tr><th>坊</th><th>所在巷</th><th>剩余分钟</th><th>更新时刻</th>${isAdmin ? "<th>补分钟</th>" : ""}</tr></thead>
      <tbody></tbody>
    </table>
    <p class="ok">${esc(state.msg)}</p>
    <p class="err">${esc(state.err)}</p>
  </div>`);
  page.querySelector(".quotafilter").value = state.quotaFilter;
  page.querySelector(".quotafilter").onchange = async (e) => {
    state.quotaFilter = e.target.value;
    try {
      await refreshQuotas();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  const tbody = page.querySelector("tbody");
  const rowHtml = (q) => `<tr>
      <td>${esc(q.workshopName)}</td>
      <td>${esc(q.alley)}</td>
      <td class="num"><span class="badge ${q.remainingMinutes === 0 ? "zero" : ""}">${q.remainingMinutes}</span></td>
      <td class="time">${fmtTime(q.updatedAt)}</td>
      ${isAdmin
        ? `<td><input class="topup" type="number" min="1" step="1" value="${esc(state.topup)}" /><button class="dotop" data-id="${q.workshopId}">补分钟</button></td>`
        : ""}
    </tr>`;
  state.quotas.forEach((q) => {
    const tr = el(`<table><tbody>${rowHtml(q)}</tbody></table>`).querySelector("tr");
    if (isAdmin) {
      tr.querySelector(".dotop").onclick = async (e) => {
        state.err = "";
        state.msg = "";
        const workshopId = Number(e.currentTarget.dataset.id);
        const raw = tr.querySelector(".topup").value;
        const minutes = Number(raw);
        if (!Number.isInteger(minutes) || minutes < 1) {
          state.err = "补分钟数须为大于 0 的整数";
          render();
          return;
        }
        try {
          const updated = await api(`/api/quotas/${workshopId}/topup`, {
            method: "POST",
            body: JSON.stringify({ minutes }),
          });
          state.msg = `${updated.workshopName} 已补 ${minutes} 分钟，现剩 ${updated.remainingMinutes} 分钟`;
          await refreshQuotas();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
    }
    tbody.append(tr);
  });
  if (state.quotas.length === 0) {
    const empty = el(`<table><tbody><tr><td colspan="${isAdmin ? 5 : 4}" class="hint">没有配额行</td></tr></tbody></table>`).querySelector("tr");
    tbody.append(empty);
  }
  box.append(page);
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    renderLogin();
    return;
  }
  app.append(topBar());
  const box = el(`<div class="wrap"></div>`);
  if (state.view === "blower") {
    renderBlower(box);
  } else if (state.board) {
    renderBoard(box);
  } else {
    box.append(el(`<p class="wrap">${esc(state.err) || "装载锅位…"}</p>`));
  }
  app.append(box);
}

if (localStorage.getItem(TOKEN_KEY)) {
  api("/api/auth/me")
    .then(async (u) => {
      state.user = u;
      state.ready = true;
      await loadWorkshops();
      render();
      return refreshBoard();
    })
    .catch((e) => {
      localStorage.removeItem(TOKEN_KEY);
      state.err = e.message;
      render();
    });
} else {
  render();
}
