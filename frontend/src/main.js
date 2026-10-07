import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };
const ROLE_LABELS = { admin: "管理员", worker: "操作工" };

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
  ready: Boolean(localStorage.getItem(TOKEN_KEY)),
  me: null,
  board: null,
  quotas: null,
  picked: null,
  peak: "96",
  err: "",
  view: location.hash.includes("blower") ? "blower" : "board",
  shopFilter: "",
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
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("zh-CN", { hour12: false });
}

function minutesHtml(mins) {
  return `<span class="mins ${mins < 1 ? "zero" : ""}">${mins}</span><span class="mins-unit">分钟</span>`;
}

async function refresh() {
  const [board, quotas] = await Promise.all([api("/api/board"), api("/api/blower/quotas")]);
  state.board = board;
  state.quotas = quotas.quotas;
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || state.board.kettles[0];
  }
  render();
}

function setView(v) {
  state.view = v;
  state.err = "";
  location.hash = v === "blower" ? "/blower" : "/board";
  render();
}

window.addEventListener("hashchange", () => {
  const v = location.hash.includes("blower") ? "blower" : "board";
  if (v !== state.view) {
    state.view = v;
    render();
  }
});

function renderLogin() {
  const box = el(`<div class="wrap">
    <h1>骨巷熬胶坊</h1>
    <p>一排熬锅作业台，原生页面，无前端框架。</p>
    <form autocomplete="off">
      <label>用户名
        <input name="u" autocomplete="off" value="${state.username}" />
      </label>
      <label>密码
        <input name="p" type="password" autocomplete="off" value="${state.password}" />
      </label>
      <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
      <button>登录</button>
    </form>
    <p class="err">${state.err}</p>
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
      state.me = data.user;
      state.ready = true;
      await refresh();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  app.append(box);
}

function renderNav(box) {
  const me = state.me || {};
  const nav = el(`<nav class="top">
    <span class="brand">骨巷熬胶坊</span>
    <button class="navbtn ${state.view === "board" ? "on" : ""}" data-v="board">锅位作业台</button>
    <button class="navbtn ${state.view === "blower" ? "on" : ""}" data-v="blower">鼓风台</button>
    <span class="who">${me.username || ""} · ${ROLE_LABELS[me.role] || ""}</span>
  </nav>`);
  nav.querySelectorAll("[data-v]").forEach((b) => {
    b.onclick = () => setView(b.dataset.v);
  });
  box.append(nav);
}

function renderBoard(box) {
  const board = state.board;
  const mins = board.blower ? board.blower.remainingMinutes : 0;
  const sec = el(`<section>
    <h1>${board.workshop}</h1>
    <p>${board.alley} · 点锅登记峰值；出胶须最近峰值 ≥ 90℃；每登一条峰值扣 1 分钟鼓风</p>
    <p class="blowerline">整坊鼓风剩余 ${minutesHtml(mins)}</p>
    <div class="row"></div>
    <section class="drawer"></section>
  </section>`);
  const row = sec.querySelector(".row");
  board.kettles.forEach((k) => {
    const btn = el(`<button class="kettle ${k.status}"><strong>${k.code}</strong><span>${LABELS[k.status]}</span></button>`);
    btn.onclick = () => {
      state.picked = k;
      render();
    };
    row.append(btn);
  });
  if (state.picked) {
    const noMin = mins < 1;
    const d = sec.querySelector(".drawer");
    d.innerHTML = `<h3>${state.picked.code} · ${LABELS[state.picked.status]}</h3>
      <p>最近峰值：${state.picked.latestPeakC ?? "无"} ℃ · ${state.picked.cookCount} 次</p>
      <p class="blowerline">鼓风剩余 ${minutesHtml(mins)}</p>
      <input id="peak" value="${state.peak}" />
      <button id="log" ${noMin ? "disabled" : ""}>登记峰值</button>
      ${noMin ? '<p class="hint">鼓风剩余分钟不足，登记峰值已被挡下；请管理员到鼓风台补分钟。</p>' : ""}
      <div>
        <button data-s="cold">冷锅</button>
        <button data-s="boiling">熬煮中</button>
        <button data-s="drawn">已出胶</button>
      </div>`;
    d.querySelector("#log").onclick = async () => {
      state.err = "";
      state.peak = d.querySelector("#peak").value;
      try {
        state.picked = await api(`/api/kettles/${state.picked.id}/cooks`, {
          method: "POST",
          body: JSON.stringify({ peakTempC: Number(state.peak) }),
        });
        await refresh();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
    d.querySelectorAll("[data-s]").forEach((b) => {
      b.onclick = async () => {
        state.err = "";
        try {
          state.picked = await api(`/api/kettles/${state.picked.id}/status`, {
            method: "POST",
            body: JSON.stringify({ status: b.dataset.s }),
          });
          await refresh();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
    });
  }
  box.append(sec);
}

function renderBlower(box) {
  const quotas = state.quotas || [];
  const isAdmin = state.me && state.me.role === "admin";
  const shops = [...new Set(quotas.map((q) => q.workshop))];
  const shown = state.shopFilter ? quotas.filter((q) => q.workshop === state.shopFilter) : quotas;
  const rows = shown
    .map(
      (q) => `<tr>
        <td>${q.workshop}</td>
        <td class="num">${minutesHtml(q.remainingMinutes)}</td>
        <td>${fmtTime(q.updatedAt)}</td>
        ${
          isAdmin
            ? `<td><input type="number" min="1" step="1" value="10" data-q="${q.id}" /><button data-top="${q.id}">补分钟</button></td>`
            : ""
        }
      </tr>`
    )
    .join("");
  const sec = el(`<section>
    <h2>鼓风台</h2>
    <p class="hint">登记一次峰值扣 1 分钟鼓风；不足即挡下，峰值不得入库。${
      isAdmin ? "管理员可把剩余分钟补回去。" : "操作工只读，补分钟请联系管理员。"
    }</p>
    <label>按坊筛
      <select id="shopFilter">
        <option value="">全部坊</option>
        ${shops.map((s) => `<option ${s === state.shopFilter ? "selected" : ""}>${s}</option>`).join("")}
      </select>
    </label>
    <table class="quota">
      <thead><tr><th>坊</th><th>剩余分钟</th><th>更新时刻</th>${isAdmin ? "<th>补分钟</th>" : ""}</tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </section>`);
  sec.querySelector("#shopFilter").onchange = (e) => {
    state.shopFilter = e.target.value;
    render();
  };
  sec.querySelectorAll("[data-top]").forEach((b) => {
    b.onclick = async () => {
      state.err = "";
      const input = sec.querySelector(`input[data-q="${b.dataset.top}"]`);
      try {
        await api(`/api/blower/quotas/${b.dataset.top}/replenish`, {
          method: "POST",
          body: JSON.stringify({ minutes: Number(input.value) }),
        });
        await refresh();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
  });
  box.append(sec);
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    renderLogin();
    return;
  }
  const box = el(`<div class="wrap"></div>`);
  renderNav(box);
  if (!state.board || !state.quotas) {
    box.append(el(`<p>${state.err || "装载锅位…"}</p>`));
  } else if (state.view === "blower") {
    renderBlower(box);
  } else {
    renderBoard(box);
  }
  box.append(el(`<p class="err">${state.err}</p>`));
  app.append(box);
}

if (state.ready) {
  (async () => {
    try {
      state.me = await api("/api/auth/me");
      await refresh();
    } catch (e) {
      state.err = e.message;
      render();
    }
  })();
} else {
  render();
}
