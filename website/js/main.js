/* ============================================================
   TythanAI — landing page interactions
   ============================================================ */
(function () {
  "use strict";

  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ============ Header: scroll state ============ */
  var header = document.getElementById("siteHeader");
  function onScroll() {
    header.classList.toggle("scrolled", window.scrollY > 8);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ============ Nav dropdowns ============ */
  var navItems = document.querySelectorAll(".nav-item.has-dropdown");

  function closeAllDropdowns(except) {
    navItems.forEach(function (item) {
      if (item !== except) {
        item.classList.remove("open");
        item.querySelector(".nav-link").setAttribute("aria-expanded", "false");
      }
    });
  }

  navItems.forEach(function (item) {
    var trigger = item.querySelector(".nav-link");
    trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      var isOpen = item.classList.toggle("open");
      trigger.setAttribute("aria-expanded", String(isOpen));
      closeAllDropdowns(item);
    });
    // Desktop hover
    item.addEventListener("mouseenter", function () {
      if (window.innerWidth > 900) {
        item.classList.add("open");
        trigger.setAttribute("aria-expanded", "true");
      }
    });
    item.addEventListener("mouseleave", function () {
      if (window.innerWidth > 900) {
        item.classList.remove("open");
        trigger.setAttribute("aria-expanded", "false");
      }
    });
  });

  document.addEventListener("click", function () { closeAllDropdowns(null); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      closeAllDropdowns(null);
      closeMobileNav();
      closeModal();
    }
  });

  /* ============ Mobile nav ============ */
  var burger = document.getElementById("burger");
  var mainNav = document.getElementById("mainNav");

  function closeMobileNav() {
    burger.classList.remove("open");
    mainNav.classList.remove("open");
    burger.setAttribute("aria-expanded", "false");
  }

  burger.addEventListener("click", function (e) {
    e.stopPropagation();
    var isOpen = burger.classList.toggle("open");
    mainNav.classList.toggle("open", isOpen);
    burger.setAttribute("aria-expanded", String(isOpen));
  });

  mainNav.querySelectorAll("a").forEach(function (link) {
    link.addEventListener("click", closeMobileNav);
  });

  /* ============ Scroll reveal ============ */
  var revealEls = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reducedMotion) {
    var revealObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          revealObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -30px 0px" });
    revealEls.forEach(function (el) { revealObserver.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add("in"); });
  }

  /* ============ Animated counters ============ */
  function animateCount(el) {
    var target = parseInt(el.getAttribute("data-count"), 10);
    var format = el.getAttribute("data-format");
    var duration = 1200;
    var start = null;

    function render(value) {
      if (format === "k") {
        el.textContent = (value / 1000).toFixed(1).replace(/\.0$/, "") + "k";
      } else {
        el.textContent = String(value);
      }
    }
    if (reducedMotion) { render(target); return; }

    function step(ts) {
      if (!start) start = ts;
      var p = Math.min((ts - start) / duration, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      render(Math.round(target * eased));
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  var countEls = document.querySelectorAll("[data-count]");
  if ("IntersectionObserver" in window) {
    var countObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          animateCount(entry.target);
          countObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });
    countEls.forEach(function (el) { countObserver.observe(el); });
  } else {
    countEls.forEach(animateCount);
  }

  /* ============ Dashboard tabs ============ */
  var tabs = document.querySelectorAll(".db-tab");
  var panels = document.querySelectorAll(".db-panel");

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      tabs.forEach(function (t) {
        t.classList.remove("active");
        t.setAttribute("aria-selected", "false");
      });
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      var name = tab.getAttribute("data-tab");
      panels.forEach(function (p) {
        p.classList.toggle("active", p.getAttribute("data-panel") === name);
      });
    });
  });

  /* ============ Findings → code panel sync ============ */
  var FINDINGS = {
    sqli: {
      file: "users.py",
      breadcrumb: "app / handlers / users.py",
      severity: "Critical",
      sevClass: "critical",
      startLine: 78,
      code: [
        { t: '<span class="tok-kw">def</span> <span class="tok-fn">get_user</span>(id):' },
        { t: '    query = <span class="tok-danger">f"SELECT * FROM users WHERE id = {id}"</span>', hl: "hl" },
        { t: "    result = db.execute(query)" },
        { t: "    <span class=\"tok-kw\">return</span> result.fetchall()" },
        { t: "" },
        { t: '<span class="tok-com"># TODO: add caching layer</span>' }
      ],
      analysis: "User input is directly interpolated into SQL query, allowing attackers to manipulate the query.",
      rec: '<span class="tok-key">query</span> = <span class="tok-str">"SELECT * FROM users WHERE id = ?"</span><br><span class="tok-key">result</span> = db.execute(query, (id,))',
      confidence: "98%"
    },
    deser: {
      file: "session.py",
      breadcrumb: "app / auth / session.py",
      severity: "High",
      sevClass: "critical",
      startLine: 210,
      code: [
        { t: '<span class="tok-kw">def</span> <span class="tok-fn">load_session</span>(cookie):' },
        { t: "    raw = base64.b64decode(cookie)" },
        { t: "    <span class=\"tok-com\"># restore user session state</span>" },
        { t: '    data = <span class="tok-danger">pickle.loads(raw)</span>', hl: "hl" },
        { t: "    <span class=\"tok-kw\">return</span> Session(data)" },
        { t: "" }
      ],
      analysis: "Untrusted cookie data is deserialized with pickle, which can execute arbitrary code during load.",
      rec: '<span class="tok-key">data</span> = json.loads(raw)  <span class="tok-com"># safe format</span><br><span class="tok-key">return</span> Session.validate(data)',
      confidence: "96%"
    },
    xss: {
      file: "login.html",
      breadcrumb: "templates / login.html",
      severity: "High",
      sevClass: "critical",
      startLine: 34,
      code: [
        { t: '&lt;<span class="tok-kw">div</span> <span class="tok-key">class</span>=<span class="tok-str">"banner"</span>&gt;' },
        { t: "  &lt;h2&gt;Welcome back&lt;/h2&gt;" },
        { t: "  &lt;p&gt;" },
        { t: '    <span class="tok-danger">{{ request.args.msg | safe }}</span>', hl: "hl" },
        { t: "  &lt;/p&gt;" },
        { t: '&lt;/<span class="tok-kw">div</span>&gt;' }
      ],
      analysis: "Query parameter is rendered with the 'safe' filter, disabling escaping and allowing script injection.",
      rec: '{{ request.args.msg }}  <span class="tok-com"># keep autoescaping on</span>',
      confidence: "94%"
    },
    secret: {
      file: "config.ts",
      breadcrumb: "src / config.ts",
      severity: "Medium",
      sevClass: "medium",
      startLine: 14,
      code: [
        { t: '<span class="tok-kw">export const</span> config = {' },
        { t: '  region: <span class="tok-str">"eu-west-1"</span>,' },
        { t: '  timeout: <span class="tok-num">3000</span>,' },
        { t: "" },
        { t: '  apiKey: <span class="tok-danger">"sk_live_9f2c…d41a"</span>,', hl: "hl-med" },
        { t: "};" }
      ],
      analysis: "A live API key is committed to source. Anyone with repo access can use or leak this credential.",
      rec: '<span class="tok-key">apiKey</span>: process.env.API_KEY,<br><span class="tok-com">// rotate the exposed key immediately</span>',
      confidence: "99%"
    },
    traversal: {
      file: "file_manager.go",
      breadcrumb: "internal / file_manager.go",
      severity: "Medium",
      sevClass: "medium",
      startLine: 87,
      code: [
        { t: '<span class="tok-kw">func</span> <span class="tok-fn">ReadUserFile</span>(name string) ([]byte, error) {' },
        { t: '  base := <span class="tok-str">"/var/data/uploads"</span>' },
        { t: "" },
        { t: '  path := <span class="tok-danger">filepath.Join(base, name)</span>', hl: "hl-med" },
        { t: "  <span class=\"tok-kw\">return</span> os.ReadFile(path)" },
        { t: "}" }
      ],
      analysis: "File name from the request can contain '../' sequences, letting attackers read files outside the uploads directory.",
      rec: '<span class="tok-key">clean</span> := filepath.Clean(name)<br><span class="tok-kw">if</span> strings.Contains(clean, <span class="tok-str">".."</span>) { <span class="tok-kw">return</span> nil, ErrBadPath }',
      confidence: "93%"
    },
    reflection: {
      file: "loader.java",
      breadcrumb: "core / loader.java",
      severity: "Low",
      sevClass: "low",
      startLine: 129,
      code: [
        { t: '<span class="tok-kw">public</span> Plugin <span class="tok-fn">load</span>(String className) {' },
        { t: "  <span class=\"tok-com\">// dynamic plugin loading</span>" },
        { t: "" },
        { t: '  Class&lt;?&gt; c = <span class="tok-danger">Class.forName(className)</span>;', hl: "hl-low" },
        { t: "  <span class=\"tok-kw\">return</span> (Plugin) c.newInstance();" },
        { t: "}" }
      ],
      analysis: "Class name comes from external configuration; instantiating arbitrary classes may expose unintended behavior.",
      rec: '<span class="tok-kw">if</span> (!ALLOWED_PLUGINS.contains(className)) <span class="tok-kw">throw new</span> SecurityException();',
      confidence: "88%"
    }
  };

  var codeBody = document.getElementById("codeBody");
  var codeFilename = document.getElementById("codeFilename");
  var codeBreadcrumb = document.getElementById("codeBreadcrumb");
  var codeSevPill = document.getElementById("codeSevPill");
  var codeSevText = document.getElementById("codeSevText");
  var aiText = document.getElementById("aiText");
  var aiRec = document.getElementById("aiRec");
  var aiConfidence = document.getElementById("aiConfidence");
  var typeTimer = null;

  function renderCode(finding) {
    codeBody.innerHTML = "";
    finding.code.forEach(function (line, i) {
      var div = document.createElement("div");
      div.className = "code-line" + (line.hl ? " " + line.hl : "");
      var ln = document.createElement("span");
      ln.className = "ln";
      ln.textContent = String(finding.startLine + i);
      var content = document.createElement("span");
      content.innerHTML = line.t || " ";
      div.appendChild(ln);
      div.appendChild(content);
      codeBody.appendChild(div);
    });
  }

  function typeText(el, text) {
    if (typeTimer) clearInterval(typeTimer);
    if (reducedMotion) { el.textContent = text; return; }
    el.textContent = "";
    el.classList.add("typing");
    var i = 0;
    typeTimer = setInterval(function () {
      i += 2;
      el.textContent = text.slice(0, i);
      if (i >= text.length) {
        clearInterval(typeTimer);
        typeTimer = null;
        el.classList.remove("typing");
      }
    }, 14);
  }

  function showFinding(key) {
    var f = FINDINGS[key];
    if (!f) return;
    codeFilename.textContent = f.file;
    codeBreadcrumb.textContent = f.breadcrumb;
    codeSevText.textContent = f.severity;
    codeSevPill.classList.remove("medium", "low");
    if (f.sevClass === "medium") codeSevPill.classList.add("medium");
    if (f.sevClass === "low") codeSevPill.classList.add("low");
    var dot = codeSevPill.querySelector(".sev-dot");
    dot.className = "sev-dot sev-" + (f.sevClass === "critical" ? "critical" : f.sevClass);
    renderCode(f);
    typeText(aiText, f.analysis);
    aiRec.innerHTML = f.rec;
    aiConfidence.textContent = f.confidence;
  }

  var findingRows = document.querySelectorAll(".finding-row");
  findingRows.forEach(function (row) {
    row.addEventListener("click", function () {
      findingRows.forEach(function (r) { r.classList.remove("active"); });
      row.classList.add("active");
      showFinding(row.getAttribute("data-finding"));
    });
  });

  // Initial render
  showFinding("sqli");

  /* ============ Sidebar / workspace clicks → toast ============ */
  function showToast(message) {
    var toast = document.getElementById("toast");
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(function () { toast.classList.remove("show"); }, 2600);
  }

  document.querySelectorAll(".db-nav-item").forEach(function (item) {
    item.addEventListener("click", function () {
      document.querySelectorAll(".db-nav-item").forEach(function (i) { i.classList.remove("active"); });
      item.classList.add("active");
      var name = item.getAttribute("data-tooltip");
      if (name !== "Overview") showToast(name + " — available in the full product. Request access to explore.");
    });
  });

  document.querySelectorAll(".db-workspace, .db-org").forEach(function (el) {
    el.addEventListener("click", function () {
      showToast("Workspace switching is available in the full product.");
    });
  });

  /* ============ Severity filter via stat cards ============ */
  var sevMap = { critical: ["sqli"], high: ["deser", "xss"], medium: ["secret", "traversal"], low: ["reflection"], info: [] };
  document.querySelectorAll(".stat-card").forEach(function (card) {
    card.addEventListener("click", function () {
      var sev = card.getAttribute("data-sev");
      var keys = sevMap[sev] || [];
      if (!keys.length) {
        showToast("Informational findings are hidden in this preview.");
        return;
      }
      // Activate findings tab
      document.querySelector('.db-tab[data-tab="findings"]').click();
      var first = document.querySelector('.finding-row[data-finding="' + keys[0] + '"]');
      if (first) first.click();
      showToast("Filtered to " + sev + " severity findings.");
    });
  });

  /* ============ Pricing billing toggle ============ */
  var billingButtons = document.querySelectorAll(".bt-option");
  var amounts = document.querySelectorAll(".price .amount[data-monthly]");

  billingButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (btn.classList.contains("active")) return;
      billingButtons.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      var mode = btn.getAttribute("data-billing");
      amounts.forEach(function (amount) {
        amount.classList.add("switching");
        setTimeout(function () {
          amount.textContent = amount.getAttribute("data-" + mode);
          amount.classList.remove("switching");
        }, 180);
      });
    });
  });

  /* ============ FAQ: smooth open/close ============ */
  document.querySelectorAll(".faq-item").forEach(function (item) {
    var summary = item.querySelector("summary");
    var body = item.querySelector(".faq-body");

    summary.addEventListener("click", function (e) {
      if (reducedMotion) return; // native toggle
      e.preventDefault();
      if (item.open) {
        body.style.maxHeight = body.scrollHeight + "px";
        requestAnimationFrame(function () {
          body.style.transition = "max-height 0.35s cubic-bezier(0.22,1,0.36,1)";
          body.style.maxHeight = "0px";
        });
        body.addEventListener("transitionend", function handler() {
          item.open = false;
          body.style.cssText = "";
          body.removeEventListener("transitionend", handler);
        });
      } else {
        item.open = true;
        var h = body.scrollHeight;
        body.style.maxHeight = "0px";
        body.style.transition = "max-height 0.35s cubic-bezier(0.22,1,0.36,1)";
        requestAnimationFrame(function () { body.style.maxHeight = h + "px"; });
        body.addEventListener("transitionend", function handler() {
          body.style.cssText = "";
          body.removeEventListener("transitionend", handler);
        });
      }
    });
  });

  /* ============ Modal ============ */
  var overlay = document.getElementById("modalOverlay");
  var modalTitle = document.getElementById("modalTitle");
  var modalSub = document.getElementById("modalSub");
  var modalSubmitText = document.getElementById("modalSubmitText");
  var modalForm = document.getElementById("modalForm");
  var modalSuccess = document.getElementById("modalSuccess");
  var formError = document.getElementById("formError");
  var companyField = document.getElementById("companyField");
  var emailInput = modalForm.querySelector('input[name="email"]');

  var MODAL_COPY = {
    access: {
      title: "Request access",
      sub: "Tell us a bit about your team and we'll get you set up.",
      submit: "Request access",
      company: true
    },
    demo: {
      title: "Book a demo",
      sub: "See TythanAI on your own codebase. 30 minutes, no slides.",
      submit: "Book a demo",
      company: true
    },
    login: {
      title: "Log in",
      sub: "Enter your work email and we'll send you a magic link.",
      submit: "Send magic link",
      company: false
    }
  };

  function openModal(kind) {
    var copy = MODAL_COPY[kind] || MODAL_COPY.access;
    modalTitle.textContent = copy.title;
    modalSub.textContent = copy.sub;
    modalSubmitText.textContent = copy.submit;
    companyField.style.display = copy.company ? "" : "none";
    modalForm.hidden = false;
    modalSub.hidden = false;
    modalSuccess.hidden = true;
    formError.classList.remove("show");
    emailInput.classList.remove("invalid");
    overlay.classList.add("open");
    overlay.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    setTimeout(function () { emailInput.focus(); }, 250);
  }

  function closeModal() {
    overlay.classList.remove("open");
    overlay.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  document.querySelectorAll("[data-modal-open]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      e.preventDefault();
      closeMobileNav();
      openModal(el.getAttribute("data-modal-open"));
    });
  });

  document.getElementById("modalClose").addEventListener("click", closeModal);
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) closeModal();
  });

  modalForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var email = emailInput.value.trim();
    var valid = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email);
    if (!valid) {
      emailInput.classList.add("invalid");
      formError.classList.add("show");
      emailInput.focus();
      return;
    }
    emailInput.classList.remove("invalid");
    formError.classList.remove("show");
    modalForm.hidden = true;
    modalSub.hidden = true;
    modalSuccess.hidden = false;
    setTimeout(function () {
      closeModal();
      setTimeout(function () { modalForm.reset(); }, 400);
      showToast("Thanks! We'll be in touch at " + email);
    }, 1800);
  });

  /* ============ Smooth anchor offset for fixed header ============ */
  document.querySelectorAll('a[href^="#"]').forEach(function (link) {
    link.addEventListener("click", function (e) {
      var id = link.getAttribute("href");
      if (id.length < 2) return;
      var target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      var top = target.getBoundingClientRect().top + window.scrollY - 84;
      window.scrollTo({ top: top, behavior: reducedMotion ? "auto" : "smooth" });
    });
  });
})();
