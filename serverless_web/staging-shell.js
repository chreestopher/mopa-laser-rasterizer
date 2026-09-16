(() => {
  if (!document.querySelector('link[rel~="icon"]')) {
    const icon = document.createElement("link");
    icon.rel = "icon";
    icon.type = "image/png";
    icon.href = "/static/docs/wizardlogo.png";
    document.head.append(icon);
  }
  const isStagingEnvironment = location.hostname.includes("serverless-staging");
  const environmentBadge = isStagingEnvironment ? "Staging" : "Production";
  for (const key of ["id_token", "refresh_token"]) {
    const legacyValue = sessionStorage.getItem(key);
    if (!localStorage.getItem(key) && legacyValue) localStorage.setItem(key, legacyValue);
    sessionStorage.removeItem(key);
  }
  window.addEventListener("storage", event => {
    if (event.storageArea !== localStorage || event.key !== "id_token") return;
    if (Boolean(event.oldValue) !== Boolean(event.newValue)) location.reload();
  });
  if (!document.querySelector('link[href^="/machine_chrome.css"]')) {
    const productionChrome = document.createElement("link");
    productionChrome.rel = "stylesheet";
    productionChrome.href = "/machine_chrome.css?v=3";
    const stagingStyles = document.querySelector('link[href^="/staging-shell.css"]');
    document.head.insertBefore(productionChrome, stagingStyles || null);
  }
  if (!document.querySelector('link[href^="/staging-shell.css"]')) {
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = "/staging-shell.css?v=1";
    document.head.append(stylesheet);
  }

  const routes = [
    { href: "/", label: "Rasterizer", match: path => ["/", "/laser-engraving-tool", "/color-laser-engraving-tool"].includes(path) },
    { href: "/experimental-laboratories", label: "Experimental Laboratories", match: path => ["/experimental-laboratories", "/fauxlographic.html", "/depthmap.html", "/color-lab.html", "/depthmap-relief-engraving-tool"].includes(path) },
    { href: "/history.html", label: "Job History", match: path => path === "/history.html" },
    { href: "/vault.html", label: "Swatch Palette Vault", match: path => path === "/vault.html" },
    { href: "/community-set", label: "Community Set", match: path => path === "/community-set" },
    { href: "/docs", label: "Docs", match: path => path === "/docs" || path.startsWith("/docs/") || path === "/release-story" },
  ];
  const pageHeroes = {
    "/": ["Serverless raster processing", "MOPA Laser Rasterizer", "Turn artwork into a laser-ready color engraving project using your saved Material Libraries and palettes.", isStagingEnvironment ? "Production-parity staging" : "Production service"],
    "/fauxlographic.html": ["Directional engraving workflow", "Fauxlographic Etching Lab", "Map artwork through a saved Fauxlographic Palette and its LightBurn Material Library.", "Experimental - active development"],
    "/depthmap.html": ["Client-side monocular depth estimation", "Depth Map Generator", "Estimate relative scene depth from a single image, inspect a relief-style projection, adjust the usable range, and export grayscale depth maps for further preparation.", "Experimental - active development"],
    "/color-lab.html": ["Controlled laser color experiments", "Color Lab", "Sweep two laser parameters at a time, measure engraved test grids, refine promising settings, and save repeatable results for your exact equipment and material.", isStagingEnvironment ? "Experimental - staging port" : "Experimental - verify all output"],
    "/experimental-laboratories": ["Workflows under active development", "Experimental Laboratories", "Explore engraving tools that extend beyond the standard Rasterizer workflow, including diffraction artwork and depth-relief preparation.", "Experimental - verify all output"],
    "/history.html": ["Retained account processing", "Job History", "Review serverless runs, processing logs, parameters, and downloads retained for the last seven days.", "Authenticated workspace"],
    "/vault.html": ["Account-owned laser parameters", "Swatch Palette Vault", "Manage Material Libraries, Color Palettes, Hatch Palettes, Depth Palettes, and Fauxlographic Palettes.", "Authenticated workspace"],
    "/community-set": ["Anonymous shared settings", "Community Set", "Explore settings voluntarily shared by laser operators using similar machines, lenses, and materials.", "Authenticated workspace"],
    "/admin.html": ["Private operational visibility", "Administration", "Review seven-day job activity, inspect retained logs, manage waiting jobs, and view the Cognito user directory.", "Authorized operator only"],
  };

  function markActiveRoute() {
    const path = location.pathname || "/";
    document.querySelectorAll("[data-shell-route]").forEach(link => {
      const route = routes.find(item => item.href === link.dataset.shellRoute);
      if (route?.match(path)) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function render() {
    if (document.querySelector(".staging-shell")) return;
    const isDocs = location.pathname === "/docs" || location.pathname.startsWith("/docs/");
    const pageClass = location.pathname === "/history.html" ? "staging-history"
      : location.pathname === "/vault.html" ? "staging-vault"
      : location.pathname === "/community-set" ? "staging-community"
      : location.pathname === "/admin.html" ? "staging-admin"
      : location.pathname === "/depthmap.html" ? "staging-depthmap"
      : location.pathname === "/color-lab.html" ? "staging-color-lab"
      : location.pathname === "/experimental-laboratories" ? "staging-experimental"
      : location.pathname === "/fauxlographic.html" ? "staging-holographic"
      : location.pathname === "/release-story" ? "staging-release-story"
      : location.pathname === "/" ? "staging-home" : "";
    if (pageClass) {
      document.body.classList.add("staging-prototype", pageClass);
      if (!document.querySelector('link[href^="/staging-pages.css"]')) {
        const pageStyles = document.createElement("link");
        pageStyles.rel = "stylesheet";
        pageStyles.href = "/staging-pages.css?v=1";
        document.head.append(pageStyles);
      }
    }
    const legacyBackLink = [...document.querySelectorAll("body > p")]
      .find(element => element.textContent.includes("Serverless staging"));
    legacyBackLink?.remove();
    const signedIn = Boolean(localStorage.getItem("id_token"));
    const header = document.createElement("header");
    header.className = "staging-shell";
    const brand = "MOPA-LASER-RASTERIZER";
    header.innerHTML = `<a class="staging-skip" href="#main-content">Skip to content</a>
      <div class="machine-control-bay machine-control-bay--standard">
        <div class="machine-power-toggle"><a class="${signedIn ? "auth-console authorized" : "login-link"}" href="/"><span class="auth-machine-switch${signedIn ? " is-on" : ""}" aria-hidden="true"></span><span>${signedIn ? "Operator authorized" : "Operator access, sign in"}</span></a><span class="staging-badge">${environmentBadge}</span></div>
        <div class="theme-toggle machine-theme-toggle"><label aria-label="Use light or dark theme"><span>Dark</span><input id="theme_switch" type="checkbox"><span class="toggle-track"></span><span>Light</span></label></div>
      </div>
      <div class="machine-brand-header">
        <h1 class="machine-brand-title"><a class="machine-brand-home" href="/" aria-label="Return to MOPA Laser Rasterizer home"><img class="machine-brand-logo" src="/static/docs/wizardlogo.png" alt=""><span class="machine-brand-letters" aria-hidden="true">${[...brand].map(letter => `<span>${letter}</span>`).join("")}</span></a></h1>
        <div class="machine-status-line">
          <div class="machine-status-lamps" role="status" aria-label="MOPA laser system indicators"><span class="machine-status-lamp machine-lamp-mopa">MOPA</span><span class="machine-status-lamp machine-lamp-laser">Laser</span><span class="machine-status-lamp machine-lamp-power">Power</span></div>
          <span class="machine-console-subtitle">SERVERLESS ${isStagingEnvironment ? "TEST" : "PRODUCTION"} CONSOLE · SERIES 79</span>
        </div>
      </div>
      <nav class="machine-nav" aria-label="Primary navigation">${routes.map(route => `<span class="machine-nav-item"><a href="${route.href}" data-shell-route="${route.href}">${route.label}</a></span>`).join("")}</nav>`;
    document.body.prepend(header);
    const loadServiceAvailability = async () => {
      try {
        const config = await fetch("/config.json", {cache: "no-store"}).then(result => result.json());
        const state = await fetch(`${config.api_url}/service-status`, {cache: "no-store"}).then(result => result.json());
        document.querySelector(".service-pause-banner")?.remove();
        if (state.status !== "paused") return;
        const banner = document.createElement("aside");
        banner.className = "service-pause-banner";
        banner.setAttribute("role", "alert");
        const resume = state.resumes_at ? new Date(Number(state.resumes_at) * 1000).toLocaleDateString(undefined, {dateStyle: "long"}) : "the first day of the next billing cycle";
        banner.textContent = `Processing is temporarily unavailable because this month's AWS spending limit was exceeded. Service is scheduled to resume automatically on ${resume}, but it may return sooner. Please check back soon.`;
        header.after(banner);
        document.body.classList.add("service-processing-paused");
      } catch (_) {}
    };
    loadServiceAvailability();
    const machineNav = header.querySelector(".machine-nav");
    const mobileNavLayout = matchMedia("(max-width: 700px)");
    let navMeasureFrame, navMeasuredWidth = -1;
    const fitMachineNav = () => {
      cancelAnimationFrame(navMeasureFrame);
      if (mobileNavLayout.matches) {
        // The longest labels always require the shared wrapped height at this
        // breakpoint. Apply it before revealing the shell to avoid a 34px to
        // 50px post-paint jump on every mobile navigation.
        machineNav.classList.add("nav-wrap-all");
        return;
      }
      machineNav.classList.remove("nav-wrap-all");
      navMeasureFrame = requestAnimationFrame(() => {
        const links = [...machineNav.querySelectorAll(".machine-nav-item > a")];
        machineNav.classList.toggle("nav-wrap-all", links.some(link => link.scrollWidth > link.clientWidth + 1));
      });
    };
    new ResizeObserver(entries => {
      const width = Math.round(entries[0].contentRect.width);
      if (width === navMeasuredWidth) return;
      navMeasuredWidth = width;
      fitMachineNav();
    }).observe(machineNav);
    mobileNavLayout.addEventListener?.("change", fitMachineNav);
    document.fonts?.ready.then(fitMachineNav);
    fitMachineNav();
    const updateAuthIndicator = authenticated => {
      const account = header.querySelector(".machine-power-toggle a");
      const powerSwitch = account.querySelector(".auth-machine-switch");
      account.className = authenticated ? "auth-console authorized" : "login-link";
      powerSwitch.classList.toggle("is-on", authenticated);
      account.querySelector("span:last-child").textContent = authenticated ? "Operator authorized" : "Operator access, sign in";
    };
    window.stagingShellSetAuthenticated = updateAuthIndicator;
    updateAuthIndicator(signedIn);
    const beginLogin = async () => {
      try {
        const config = await fetch("/config.json", { cache: "no-store" }).then(response => response.json());
        const redirectUri = new URL("/", location.origin).href;
        const requestedTask = new URLSearchParams(location.search).get("task");
        if (requestedTask) sessionStorage.setItem("pending_task", requestedTask);
        if (location.pathname !== "/") sessionStorage.setItem("post_login_path", location.pathname + location.search);
        const random = crypto.getRandomValues(new Uint8Array(48));
        const encode = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
        const verifier = encode(random);
        sessionStorage.setItem("pkce_verifier", verifier);
        sessionStorage.setItem("pkce_redirect_uri", redirectUri);
        const challenge = encode(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
        const query = new URLSearchParams({
          client_id: config.client_id,
          response_type: "code",
          scope: "openid email",
          redirect_uri: redirectUri,
          code_challenge_method: "S256",
          code_challenge: challenge,
        });
        location.href = `https://${config.cognito_domain}/oauth2/authorize?${query}`;
      } catch (_) {
        location.href = "/";
      }
    };
    window.stagingShellBeginLogin = beginLogin;
    document.querySelectorAll("[data-registered-access-login]").forEach(link => {
      link.addEventListener("click", event => {
        event.preventDefault();
        beginLogin();
      });
    });
    const account = header.querySelector(".machine-power-toggle a");
    account.addEventListener("click", async event => {
      event.preventDefault();
      if (!localStorage.getItem("id_token")) {
        await beginLogin();
        return;
      }
      updateAuthIndicator(false);
      localStorage.removeItem("id_token");
      localStorage.removeItem("refresh_token");
      sessionStorage.clear();
      try {
        const config = await fetch("/config.json", { cache: "no-store" }).then(response => response.json());
        const logoutUri = new URL("/", location.origin).href;
        const query = new URLSearchParams({
          client_id: config.client_id,
          logout_uri: logoutUri,
        });
        location.href = `https://${config.cognito_domain}/logout?${query}`;
      } catch (_) {
        location.href = "/";
      }
    });
    const heroData = pageHeroes[location.pathname];
    if (heroData) {
      const oldTitle = [...document.body.children].find(element => element.tagName === "H1");
      let sibling = oldTitle?.nextElementSibling;
      oldTitle?.remove();
      while (sibling?.tagName === "P" && !sibling.id) {
        const next = sibling.nextElementSibling;
        sibling.remove();
        sibling = next;
      }
      const hero = document.createElement("section");
      hero.className = "panel hero staging-page-hero";
      hero.innerHTML = `<p class="eyebrow">${heroData[0]}</p><h1>${heroData[1]}</h1><p>${heroData[2]}</p><span class="experimental">${heroData[3]}</span>`;
      header.after(hero);
    }
    let pageShell = null;
    if (pageClass) {
      pageShell = document.createElement("main");
      pageShell.className = "staging-page-shell";
      const pageElements = [...document.body.children].filter(element =>
        element !== header && element.tagName !== "SCRIPT"
      );
      header.after(pageShell);
      pageElements.forEach(element => pageShell.append(element));

      const machineShell = document.createElement("div");
      machineShell.className = "staging-machine-shell";
      header.before(machineShell);
      machineShell.append(header, pageShell);
    } else if (isDocs) {
      const docsShell = document.querySelector(".docs-shell");
      const docsFooter = document.querySelector(".docs-footer");
      if (docsShell) {
        const machineShell = document.createElement("div");
        machineShell.className = "staging-machine-shell staging-machine-shell--docs";
        header.before(machineShell);
        machineShell.append(header, docsShell);
        if (docsFooter) machineShell.append(docsFooter);
      }
    }
    const content = pageShell || document.querySelector("main") || [...document.body.children]
      .find(element => element !== header && element.tagName !== "SCRIPT");
    if (content && !document.querySelector("#main-content")) content.id = "main-content";
    const themeSwitch = document.querySelector("#theme_switch");
    let savedTheme = "dark";
    try { savedTheme = localStorage.getItem("mopa-machine-theme") || "dark"; } catch (_) {}
    const applyTheme = light => {
      document.body.classList.toggle("light-machine", light);
      themeSwitch.checked = light;
    };
    applyTheme(savedTheme === "light");
    themeSwitch.addEventListener("change", () => {
      applyTheme(themeSwitch.checked);
      try { localStorage.setItem("mopa-machine-theme", themeSwitch.checked ? "light" : "dark"); } catch (_) {}
    });
    markActiveRoute();
    document.documentElement.classList.remove("staging-shell-pending");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render, { once: true });
  else render();
  addEventListener("hashchange", markActiveRoute);
})();
