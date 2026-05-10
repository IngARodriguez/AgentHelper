// Perfil Firefox para uso local con docker compose. Foco: máxima estabilidad
// y eliminar prompts/diálogos que paralizan al agente. NO recortamos memoria
// ni cache — Firefox usa todo lo que necesite del host.

// ─── GPU / aceleración (necesario en Xvfb, no hay GPU virtual) ───────────────
// Sin GPU. WebRender intenta usar OpenGL → falla → crash. Es la causa #1 de
// crashes en headless con Xvfb.
user_pref("gfx.webrender.all", false);
user_pref("gfx.webrender.enabled", false);
user_pref("gfx.webrender.software", false);
user_pref("layers.acceleration.disabled", true);
user_pref("layers.acceleration.force-enabled", false);
user_pref("media.hardware-video-decoding.enabled", false);
user_pref("media.gpu-process-decoder", false);

// ─── Telemetry / data collection / studies ───────────────────────────────────
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);
user_pref("toolkit.telemetry.archive.enabled", false);
user_pref("toolkit.telemetry.bhrPing.enabled", false);
user_pref("toolkit.telemetry.firstShutdownPing.enabled", false);
user_pref("toolkit.telemetry.newProfilePing.enabled", false);
user_pref("toolkit.telemetry.shutdownPingSender.enabled", false);
user_pref("toolkit.telemetry.updatePing.enabled", false);
user_pref("toolkit.telemetry.coverage.opt-out", true);
user_pref("toolkit.coverage.opt-out", true);
user_pref("toolkit.coverage.endpoint.base", "");
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("app.shield.optoutstudies.enabled", false);
user_pref("app.normandy.enabled", false);
user_pref("app.normandy.api_url", "");

// ─── Crash reports (no podemos contestar el diálogo) ─────────────────────────
user_pref("breakpad.reportURL", "");
user_pref("browser.tabs.crashReporting.sendReport", false);
user_pref("browser.crashReports.unsubmittedCheck.enabled", false);
user_pref("browser.crashReports.unsubmittedCheck.autoSubmit2", false);
user_pref("dom.ipc.plugins.reportCrashURL", false);

// ─── No restaurar tabs tras crash (el diálogo bloquea el arranque) ───────────
user_pref("browser.sessionstore.max_resumed_crashes", 0);
user_pref("browser.sessionstore.resume_from_crash", false);

// ─── Anti-crash en navegación / tab crashes ──────────────────────────────────
// Si una pestaña crashea, no muestra una página intermedia que confunde al agente.
user_pref("browser.tabs.unloadOnLowMemory", false);
// Bloqueo de autoplay (audio/video). En headless el codec puede crashear.
user_pref("media.autoplay.default", 5);
user_pref("media.autoplay.blocking_policy", 2);
// Captive portal probe corre en background y a veces bloquea — apagado.
user_pref("network.captive-portal-service.enabled", false);
user_pref("network.connectivity-service.enabled", false);
// Sin diálogo de "página no responde" — el agente esperará.
user_pref("dom.max_script_run_time", 0);
user_pref("dom.max_chrome_script_run_time", 0);
user_pref("dom.max_ext_content_script_run_time", 0);

// ─── Funcionalidad innecesaria / pop-ups ─────────────────────────────────────
user_pref("extensions.pocket.enabled", false);
user_pref("identity.fxaccounts.enabled", false);
user_pref("browser.discovery.enabled", false);
user_pref("browser.newtabpage.activity-stream.feeds.section.topstories", false);
user_pref("browser.newtabpage.activity-stream.feeds.snippets", false);
user_pref("browser.newtabpage.activity-stream.section.highlights.includePocket", false);
user_pref("browser.newtabpage.activity-stream.showSponsored", false);
user_pref("browser.newtabpage.activity-stream.showSponsoredTopSites", false);
user_pref("browser.uitour.enabled", false);
user_pref("browser.contentblocking.report.show_mobile_app", false);

// Sin notificaciones push / DRM (prompts y módulos opcionales que crashean).
user_pref("dom.push.enabled", false);
user_pref("dom.webnotifications.enabled", false);
user_pref("media.gmp-gmpopenh264.enabled", false);
user_pref("media.gmp-widevinecdm.enabled", false);
user_pref("media.eme.enabled", false);

// ─── Inicio / página de bienvenida ───────────────────────────────────────────
user_pref("browser.startup.homepage", "https://duckduckgo.com");
user_pref("browser.startup.page", 1);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("startup.homepage_override_url", "");
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.newtab.url", "about:blank");

// ─── Updates: evitar prompts y descargas en background ───────────────────────
user_pref("app.update.auto", false);
user_pref("app.update.enabled", false);
user_pref("app.update.checkInstallTime", false);
user_pref("app.update.silent", true);
user_pref("app.update.staging.enabled", false);
user_pref("app.update.service.enabled", false);
user_pref("extensions.update.enabled", false);
user_pref("extensions.update.autoUpdateDefault", false);
user_pref("browser.search.update", false);

// ─── DevTools para pentesting web ────────────────────────────────────────────
// El agente usa DevTools (F12) para análisis web. Estas prefs hacen el flujo
// más útil: cache off al abrir DevTools, no truncar responses, persistir logs.
user_pref("devtools.cache.disabled", true);
user_pref("devtools.netmonitor.persistlog", true);
user_pref("devtools.netmonitor.responseBodyLimit", 0);
user_pref("devtools.netmonitor.requestBodyLimit", 0);
user_pref("devtools.webconsole.timestampMessages", true);
user_pref("devtools.webconsole.input.editor", false);
user_pref("devtools.toolbox.host", "bottom");
user_pref("devtools.toolbox.previousHost", "bottom");
user_pref("devtools.toolbox.footer.height", 350);
// Habilitar inspección del chrome del navegador (útil para tests avanzados).
user_pref("devtools.chrome.enabled", true);
user_pref("devtools.debugger.remote-enabled", true);
// No pedir confirmación al pegar grandes textos en la consola.
user_pref("devtools.selfxss.count", 100);
// Source maps activadas (cuando los servidores los expongan, ver código original).
user_pref("devtools.source-map.client-service.enabled", true);
// Welcome / what's new de DevTools off.
user_pref("devtools.whatsnew.enabled", false);
user_pref("devtools.onboarding.telemetry.logged", true);

// ─── Permitir instalar extensiones desde el navegador (addons.mozilla.org) ───
// El agente puede ir a AMO e instalar Wappalyzer / FoxyProxy / HackTools si
// los necesita. Por defecto Firefox-ESR ya permite addons firmados.
user_pref("xpinstall.signatures.required", true);
user_pref("extensions.autoDisableScopes", 0);
user_pref("extensions.enabledScopes", 15);

// ─── Prompts y modales que paralizan al agente ───────────────────────────────
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.tabs.warnOnCloseOtherTabs", false);
user_pref("browser.warnOnQuit", false);
user_pref("browser.warnOnQuitShortcut", false);
user_pref("browser.tabs.closeWindowWithLastTab", false);
user_pref("dom.disable_beforeunload", true);
user_pref("dom.successive_dialog_time_limit", 0);
user_pref("permissions.default.geo", 2);
user_pref("permissions.default.camera", 2);
user_pref("permissions.default.microphone", 2);
user_pref("permissions.default.desktop-notification", 2);
user_pref("geo.enabled", false);
user_pref("general.warnOnAboutConfig", false);
