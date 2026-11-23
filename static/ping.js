/* keep-alive ping: only the local exe needs it (to know when its window closes); never on the web */
if (/^(127\.0\.0\.1|localhost)$/.test(location.hostname)) { setInterval(() => fetch('/api/ping').catch(() => { }), 10000); fetch('/api/ping').catch(() => { }); }
